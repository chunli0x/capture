//! Tap Farm stake program - the SKR quality bond.
//!
//! Gold-standard tasks *detect* bad labeling, but detection with no cost is a
//! treadmill: a scripter whose accuracy collapses just funds a new wallet. A
//! bond makes bad labeling expensive, which is what makes the network's data
//! worth buying - and it is why the reward asset has to be SKR specifically
//! rather than any stablecoin. A bond's deterrent value comes from being
//! denominated in something whose worth tracks the network's success.
//!
//! Lifecycle:
//!
//! ```text
//!   stake ──► working at the staked tier
//!     │
//!     ├─ slash ──────────► bond reduced, tokens attributed to the reward pool
//!     │
//!     └─ request_unstake ──► cooldown ──► withdraw
//!                              ▲
//!                              └── slashing still reaches the bond here
//! ```
//!
//! That last point is the reason the cooldown exists, and the one design
//! decision worth defending: `request_unstake` does **not** reduce the bond.
//! If it did, a contributor could submit garbage and request an exit in the
//! same breath, and the bond would be gone before their accuracy had been
//! scored. Instead the bond stays slashable for the whole cooldown, and
//! `withdraw` pays out whatever survives.

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, TransferChecked};

declare_id!("9brNsPyt6cb9yVv9kFNvN9xwd9ww41BJqiyG4DpCR1aQ");

pub const CONFIG_SEED: &[u8] = b"config";
pub const STAKE_SEED: &[u8] = b"stake";
pub const VAULT_SEED: &[u8] = b"vault";

/// Reward multiplier applied to a staked contributor's per-task rate. The
/// backend reads the tier and prices tasks accordingly; the program only owns
/// the bond.
pub const STAKED_TIER_MULTIPLIER: u8 = 4;

/// Decision logic, kept free of Anchor types so it can be tested with a plain
/// `cargo test` on the host rather than only in a validator.
pub mod logic {
    /// Tier 0 is the unstaked onboarding tier; tier 1 unlocks the higher rate.
    ///
    /// Onboarding must work at tier 0 with no bond at all, or a new contributor
    /// is asked to stake a token they have no way to have earned yet.
    pub fn tier_for(staked: u64, min_stake: u64) -> u8 {
        if min_stake > 0 && staked >= min_stake {
            1
        } else {
            0
        }
    }

    /// Whether the cooldown has elapsed. Saturating so a clock that moves
    /// backwards cannot wrap into "ready".
    pub fn cooldown_elapsed(requested_at: i64, now: i64, cooldown_seconds: i64) -> bool {
        if requested_at <= 0 {
            return false;
        }
        now.saturating_sub(requested_at) >= cooldown_seconds
    }

    /// Slashing is clamped to what is actually staked, so an over-large request
    /// takes the whole bond instead of failing or underflowing.
    pub fn clamp_slash(staked: u64, requested: u64) -> u64 {
        requested.min(staked)
    }

    /// Payout is capped by the surviving bond: a slash during cooldown reduces
    /// what a pending unstake can withdraw.
    pub fn withdrawable(requested_amount: u64, staked: u64) -> u64 {
        requested_amount.min(staked)
    }
}

#[program]
pub mod tapfarm_stake {
    use super::*;

    pub fn initialize(
        ctx: Context<Initialize>,
        min_stake: u64,
        cooldown_seconds: i64,
        slash_authority: Pubkey,
    ) -> Result<()> {
        require!(min_stake > 0, StakeError::InvalidMinStake);
        require!(cooldown_seconds >= 0, StakeError::InvalidCooldown);

        let config = &mut ctx.accounts.config;
        config.admin = ctx.accounts.admin.key();
        config.slash_authority = slash_authority;
        config.skr_mint = ctx.accounts.skr_mint.key();
        config.min_stake = min_stake;
        config.cooldown_seconds = cooldown_seconds;
        config.total_staked = 0;
        config.slashed_pool = 0;
        config.bump = ctx.bumps.config;
        Ok(())
    }

    /// Move SKR from the contributor into the vault. The contributor signs, so
    /// staking is a genuine user-authorized transaction.
    pub fn stake(ctx: Context<Stake>, amount: u64) -> Result<()> {
        require!(amount > 0, StakeError::ZeroAmount);

        token::transfer_checked(
            CpiContext::new(
                ctx.accounts.token_program.key(),
                TransferChecked {
                    from: ctx.accounts.contributor_tokens.to_account_info(),
                    mint: ctx.accounts.skr_mint.to_account_info(),
                    to: ctx.accounts.vault.to_account_info(),
                    authority: ctx.accounts.contributor.to_account_info(),
                },
            ),
            amount,
            ctx.accounts.skr_mint.decimals,
        )?;

        let stake_account = &mut ctx.accounts.stake_account;
        if stake_account.contributor == Pubkey::default() {
            stake_account.contributor = ctx.accounts.contributor.key();
            stake_account.bump = ctx.bumps.stake_account;
            stake_account.staked_at = Clock::get()?.unix_timestamp;
        }
        stake_account.amount = stake_account
            .amount
            .checked_add(amount)
            .ok_or(StakeError::MathOverflow)?;

        let config = &mut ctx.accounts.config;
        config.total_staked = config
            .total_staked
            .checked_add(amount)
            .ok_or(StakeError::MathOverflow)?;

        emit!(Staked {
            contributor: stake_account.contributor,
            amount,
            total: stake_account.amount,
            tier: logic::tier_for(stake_account.amount, config.min_stake),
        });
        Ok(())
    }

    /// Begin the cooldown. Deliberately does not reduce the bond - see the
    /// module docs.
    pub fn request_unstake(ctx: Context<ModifyStake>, amount: u64) -> Result<()> {
        let stake_account = &mut ctx.accounts.stake_account;
        require!(amount > 0, StakeError::ZeroAmount);
        require!(amount <= stake_account.amount, StakeError::InsufficientStake);

        stake_account.unstake_amount = amount;
        stake_account.unstake_requested_at = Clock::get()?.unix_timestamp;

        emit!(UnstakeRequested {
            contributor: stake_account.contributor,
            amount,
            available_at: stake_account.unstake_requested_at
                + ctx.accounts.config.cooldown_seconds,
        });
        Ok(())
    }

    pub fn withdraw(ctx: Context<Withdraw>) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let config_cooldown = ctx.accounts.config.cooldown_seconds;

        {
            let stake_account = &ctx.accounts.stake_account;
            require!(
                stake_account.unstake_requested_at > 0,
                StakeError::NoPendingUnstake
            );
            require!(
                logic::cooldown_elapsed(
                    stake_account.unstake_requested_at,
                    now,
                    config_cooldown
                ),
                StakeError::CooldownActive
            );
        }

        let payout = logic::withdrawable(
            ctx.accounts.stake_account.unstake_amount,
            ctx.accounts.stake_account.amount,
        );
        require!(payout > 0, StakeError::NothingToWithdraw);

        let bump = ctx.accounts.config.bump;
        let signer_seeds: &[&[&[u8]]] = &[&[CONFIG_SEED, &[bump]]];

        token::transfer_checked(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                TransferChecked {
                    from: ctx.accounts.vault.to_account_info(),
                    mint: ctx.accounts.skr_mint.to_account_info(),
                    to: ctx.accounts.contributor_tokens.to_account_info(),
                    authority: ctx.accounts.config.to_account_info(),
                },
                signer_seeds,
            ),
            payout,
            ctx.accounts.skr_mint.decimals,
        )?;

        let stake_account = &mut ctx.accounts.stake_account;
        stake_account.amount = stake_account
            .amount
            .checked_sub(payout)
            .ok_or(StakeError::MathOverflow)?;
        stake_account.unstake_amount = 0;
        stake_account.unstake_requested_at = 0;

        let config = &mut ctx.accounts.config;
        config.total_staked = config.total_staked.saturating_sub(payout);

        emit!(Withdrawn {
            contributor: stake_account.contributor,
            amount: payout,
            remaining: stake_account.amount,
        });
        Ok(())
    }

    /// Burn part of a bond. Called by the slash authority when a contributor's
    /// rolling gold-standard accuracy falls below threshold; the scoring rules
    /// live in the backend (see tapfarm/scoring.py), which is the oracle here.
    ///
    /// Slashed tokens stay in the vault and are attributed to `slashed_pool`,
    /// to be paid back out as campaign rewards: honest contributors are paid
    /// out of dishonest ones.
    pub fn slash(ctx: Context<Slash>, amount: u64) -> Result<()> {
        require!(amount > 0, StakeError::ZeroAmount);

        let slashed = logic::clamp_slash(ctx.accounts.stake_account.amount, amount);
        require!(slashed > 0, StakeError::NothingToSlash);

        let stake_account = &mut ctx.accounts.stake_account;
        stake_account.amount = stake_account
            .amount
            .checked_sub(slashed)
            .ok_or(StakeError::MathOverflow)?;

        let config = &mut ctx.accounts.config;
        config.total_staked = config.total_staked.saturating_sub(slashed);
        config.slashed_pool = config
            .slashed_pool
            .checked_add(slashed)
            .ok_or(StakeError::MathOverflow)?;

        emit!(Slashed {
            contributor: stake_account.contributor,
            amount: slashed,
            remaining: stake_account.amount,
        });
        Ok(())
    }
}

#[account]
#[derive(InitSpace)]
pub struct Config {
    pub admin: Pubkey,
    pub slash_authority: Pubkey,
    pub skr_mint: Pubkey,
    pub min_stake: u64,
    pub cooldown_seconds: i64,
    pub total_staked: u64,
    pub slashed_pool: u64,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct StakeAccount {
    pub contributor: Pubkey,
    pub amount: u64,
    pub staked_at: i64,
    pub unstake_requested_at: i64,
    pub unstake_amount: u64,
    pub bump: u8,
}

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub admin: Signer<'info>,

    #[account(
        init,
        payer = admin,
        space = 8 + Config::INIT_SPACE,
        seeds = [CONFIG_SEED],
        bump,
    )]
    pub config: Account<'info, Config>,

    #[account(
        init,
        payer = admin,
        seeds = [VAULT_SEED],
        bump,
        token::mint = skr_mint,
        token::authority = config,
    )]
    pub vault: Account<'info, TokenAccount>,

    pub skr_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct Stake<'info> {
    #[account(mut)]
    pub contributor: Signer<'info>,

    #[account(
        mut,
        seeds = [CONFIG_SEED],
        bump = config.bump,
        has_one = skr_mint,
    )]
    pub config: Account<'info, Config>,

    #[account(
        init_if_needed,
        payer = contributor,
        space = 8 + StakeAccount::INIT_SPACE,
        seeds = [STAKE_SEED, contributor.key().as_ref()],
        bump,
    )]
    pub stake_account: Account<'info, StakeAccount>,

    #[account(mut, seeds = [VAULT_SEED], bump)]
    pub vault: Account<'info, TokenAccount>,

    #[account(
        mut,
        constraint = contributor_tokens.mint == config.skr_mint @ StakeError::WrongMint,
        constraint = contributor_tokens.owner == contributor.key() @ StakeError::WrongOwner,
    )]
    pub contributor_tokens: Account<'info, TokenAccount>,

    pub skr_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct ModifyStake<'info> {
    pub contributor: Signer<'info>,

    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        seeds = [STAKE_SEED, contributor.key().as_ref()],
        bump = stake_account.bump,
        has_one = contributor,
    )]
    pub stake_account: Account<'info, StakeAccount>,
}

#[derive(Accounts)]
pub struct Withdraw<'info> {
    pub contributor: Signer<'info>,

    #[account(
        mut,
        seeds = [CONFIG_SEED],
        bump = config.bump,
        has_one = skr_mint,
    )]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        seeds = [STAKE_SEED, contributor.key().as_ref()],
        bump = stake_account.bump,
        has_one = contributor,
    )]
    pub stake_account: Account<'info, StakeAccount>,

    #[account(mut, seeds = [VAULT_SEED], bump)]
    pub vault: Account<'info, TokenAccount>,

    #[account(
        mut,
        constraint = contributor_tokens.mint == config.skr_mint @ StakeError::WrongMint,
        constraint = contributor_tokens.owner == contributor.key() @ StakeError::WrongOwner,
    )]
    pub contributor_tokens: Account<'info, TokenAccount>,

    pub skr_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct Slash<'info> {
    /// Only the configured slash authority may reduce a bond.
    pub slash_authority: Signer<'info>,

    #[account(
        mut,
        seeds = [CONFIG_SEED],
        bump = config.bump,
        constraint = config.slash_authority == slash_authority.key() @ StakeError::NotSlashAuthority,
    )]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        seeds = [STAKE_SEED, stake_account.contributor.as_ref()],
        bump = stake_account.bump,
    )]
    pub stake_account: Account<'info, StakeAccount>,
}

#[event]
pub struct Staked {
    pub contributor: Pubkey,
    pub amount: u64,
    pub total: u64,
    pub tier: u8,
}

#[event]
pub struct UnstakeRequested {
    pub contributor: Pubkey,
    pub amount: u64,
    pub available_at: i64,
}

#[event]
pub struct Withdrawn {
    pub contributor: Pubkey,
    pub amount: u64,
    pub remaining: u64,
}

#[event]
pub struct Slashed {
    pub contributor: Pubkey,
    pub amount: u64,
    pub remaining: u64,
}

#[error_code]
pub enum StakeError {
    #[msg("minimum stake must be greater than zero")]
    InvalidMinStake,
    #[msg("cooldown cannot be negative")]
    InvalidCooldown,
    #[msg("amount must be greater than zero")]
    ZeroAmount,
    #[msg("stake is smaller than the requested amount")]
    InsufficientStake,
    #[msg("no unstake has been requested")]
    NoPendingUnstake,
    #[msg("cooldown has not elapsed")]
    CooldownActive,
    #[msg("nothing left to withdraw")]
    NothingToWithdraw,
    #[msg("nothing left to slash")]
    NothingToSlash,
    #[msg("signer is not the slash authority")]
    NotSlashAuthority,
    #[msg("token account is for the wrong mint")]
    WrongMint,
    #[msg("token account has the wrong owner")]
    WrongOwner,
    #[msg("arithmetic overflow")]
    MathOverflow,
}

#[cfg(test)]
mod tests {
    use super::logic::*;

    const MIN: u64 = 100_000;

    #[test]
    fn unstaked_contributor_is_tier_zero() {
        assert_eq!(tier_for(0, MIN), 0);
    }

    #[test]
    fn below_minimum_is_still_tier_zero() {
        assert_eq!(tier_for(MIN - 1, MIN), 0);
    }

    #[test]
    fn exactly_the_minimum_unlocks_the_staked_tier() {
        assert_eq!(tier_for(MIN, MIN), 1);
    }

    #[test]
    fn above_the_minimum_stays_tier_one() {
        assert_eq!(tier_for(MIN * 50, MIN), 1);
    }

    #[test]
    fn a_zero_minimum_never_grants_a_tier_for_free() {
        // Guards against a misconfigured config making everyone staked.
        assert_eq!(tier_for(0, 0), 0);
    }

    #[test]
    fn cooldown_is_not_elapsed_without_a_request() {
        assert!(!cooldown_elapsed(0, 1_000_000, 60));
    }

    #[test]
    fn cooldown_is_not_elapsed_early() {
        assert!(!cooldown_elapsed(1_000, 1_059, 60));
    }

    #[test]
    fn cooldown_elapses_exactly_on_the_boundary() {
        assert!(cooldown_elapsed(1_000, 1_060, 60));
    }

    #[test]
    fn a_backwards_clock_cannot_elapse_the_cooldown() {
        assert!(!cooldown_elapsed(1_000, 500, 60));
    }

    #[test]
    fn zero_cooldown_elapses_immediately() {
        assert!(cooldown_elapsed(1_000, 1_000, 0));
    }

    #[test]
    fn slash_takes_the_requested_amount() {
        assert_eq!(clamp_slash(1_000, 400), 400);
    }

    #[test]
    fn slash_is_capped_at_the_whole_bond() {
        assert_eq!(clamp_slash(1_000, 5_000), 1_000);
    }

    #[test]
    fn slashing_an_empty_bond_yields_nothing() {
        assert_eq!(clamp_slash(0, 5_000), 0);
    }

    #[test]
    fn withdrawal_pays_the_requested_amount_when_unslashed() {
        assert_eq!(withdrawable(600, 1_000), 600);
    }

    #[test]
    fn a_slash_during_cooldown_reduces_the_payout() {
        // Requested 600, then slashed down to 250: only 250 survives.
        assert_eq!(withdrawable(600, 250), 250);
    }

    #[test]
    fn a_full_slash_during_cooldown_leaves_nothing_to_withdraw() {
        assert_eq!(withdrawable(600, 0), 0);
    }
}
