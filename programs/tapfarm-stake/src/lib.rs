//! Tap stake program - two stakes, two jobs.
//!
//! **TAP** is our token and the slashable quality bond. Gold-standard tasks
//! detect bad labeling, but detection with no cost is a treadmill: a scripter
//! whose accuracy collapses just funds a new wallet. The bond makes bad
//! labeling expensive, which is what makes the data worth buying.
//!
//! **SKR** is Solana Mobile's token and is **never slashed**. It is an access
//! stake: locking it signals commitment to the platform and unlocks referral
//! earnings. Burning someone else's token as a punishment is not ours to do,
//! so `slash` can only ever touch the TAP vault - enforced here rather than by
//! convention.
//!
//! ```text
//!   stake(Tap) ──► quality tier          stake(Skr) ──► referral eligibility
//!     │                                     │
//!     ├─ slash ──► burned to reward pool    │  (never slashable)
//!     │                                     │
//!     └─ request_unstake ─► cooldown ─► withdraw ◄──────┘
//!                             ▲
//!                             └── slashing still reaches the TAP bond here
//! ```
//!
//! `request_unstake` deliberately does **not** reduce the bond. If it did, a
//! contributor could submit garbage and request an exit in the same breath, and
//! the bond would be gone before their accuracy was scored. The bond stays
//! slashable for the whole cooldown; `withdraw` pays out whatever survives.

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, TransferChecked};

declare_id!("9brNsPyt6cb9yVv9kFNvN9xwd9ww41BJqiyG4DpCR1aQ");

pub const CONFIG_SEED: &[u8] = b"config";
pub const STAKE_SEED: &[u8] = b"stake";
pub const VAULT_SEED: &[u8] = b"vault";

/// Which stake an instruction acts on. Vaults are per-mint, so this only
/// selects which mint the passed accounts must match.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, Debug)]
pub enum Asset {
    Tap,
    Skr,
}

/// Decision logic, kept free of Anchor types so it can be tested with a plain
/// `cargo test` on the host rather than only in a validator.
pub mod logic {
    /// Tier 0 is the unstaked onboarding tier; tier 1 unlocks the higher rate.
    ///
    /// Keyed on the TAP bond alone: what earns a contributor better-paid work
    /// is collateral we can actually slash if the work is bad. Holding SKR says
    /// nothing about label quality.
    pub fn tier_for(tap_staked: u64, min_tap_stake: u64) -> u8 {
        if min_tap_stake > 0 && tap_staked >= min_tap_stake {
            1
        } else {
            0
        }
    }

    /// Referral earnings require both stakes: a slashable bond so a referrer
    /// has something at risk, and an SKR stake as platform commitment.
    pub fn referral_eligible(
        tap_staked: u64,
        min_tap_stake: u64,
        skr_staked: u64,
        min_skr_stake: u64,
    ) -> bool {
        tier_for(tap_staked, min_tap_stake) == 1
            && min_skr_stake > 0
            && skr_staked >= min_skr_stake
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
        min_tap_stake: u64,
        min_skr_stake: u64,
        cooldown_seconds: i64,
        slash_authority: Pubkey,
    ) -> Result<()> {
        require!(min_tap_stake > 0, StakeError::InvalidMinStake);
        require!(min_skr_stake > 0, StakeError::InvalidMinStake);
        require!(cooldown_seconds >= 0, StakeError::InvalidCooldown);
        require_keys_neq!(
            ctx.accounts.tap_mint.key(),
            ctx.accounts.skr_mint.key(),
            StakeError::DuplicateMint
        );

        let config = &mut ctx.accounts.config;
        config.admin = ctx.accounts.admin.key();
        config.slash_authority = slash_authority;
        config.tap_mint = ctx.accounts.tap_mint.key();
        config.skr_mint = ctx.accounts.skr_mint.key();
        config.min_tap_stake = min_tap_stake;
        config.min_skr_stake = min_skr_stake;
        config.cooldown_seconds = cooldown_seconds;
        config.total_tap_staked = 0;
        config.total_skr_staked = 0;
        config.slashed_pool = 0;
        config.bump = ctx.bumps.config;
        Ok(())
    }

    /// Move tokens from the contributor into the vault for that mint. The
    /// contributor signs, so staking is a genuine user-authorized transaction.
    pub fn stake(ctx: Context<Stake>, asset: Asset, amount: u64) -> Result<()> {
        require!(amount > 0, StakeError::ZeroAmount);
        ctx.accounts.config.require_mint(asset, ctx.accounts.mint.key())?;

        token::transfer_checked(
            CpiContext::new(
                ctx.accounts.token_program.key(),
                TransferChecked {
                    from: ctx.accounts.contributor_tokens.to_account_info(),
                    mint: ctx.accounts.mint.to_account_info(),
                    to: ctx.accounts.vault.to_account_info(),
                    authority: ctx.accounts.contributor.to_account_info(),
                },
            ),
            amount,
            ctx.accounts.mint.decimals,
        )?;

        let now = Clock::get()?.unix_timestamp;
        let stake_account = &mut ctx.accounts.stake_account;
        if stake_account.contributor == Pubkey::default() {
            stake_account.contributor = ctx.accounts.contributor.key();
            stake_account.bump = ctx.bumps.stake_account;
            stake_account.staked_at = now;
        }

        let position = stake_account.position_mut(asset);
        position.amount = position
            .amount
            .checked_add(amount)
            .ok_or(StakeError::MathOverflow)?;
        let new_total = position.amount;

        let config = &mut ctx.accounts.config;
        config.add_total(asset, amount)?;

        emit!(Staked {
            contributor: ctx.accounts.contributor.key(),
            asset,
            amount,
            total: new_total,
            tier: logic::tier_for(
                ctx.accounts.stake_account.tap.amount,
                config.min_tap_stake
            ),
        });
        Ok(())
    }

    /// Begin the cooldown for one asset. Deliberately does not reduce the
    /// staked amount - see the module docs.
    pub fn request_unstake(
        ctx: Context<ModifyStake>,
        asset: Asset,
        amount: u64,
    ) -> Result<()> {
        require!(amount > 0, StakeError::ZeroAmount);
        let cooldown = ctx.accounts.config.cooldown_seconds;
        let now = Clock::get()?.unix_timestamp;

        let contributor = ctx.accounts.stake_account.contributor;
        let position = ctx.accounts.stake_account.position_mut(asset);
        require!(amount <= position.amount, StakeError::InsufficientStake);

        position.unstake_amount = amount;
        position.unstake_requested_at = now;

        emit!(UnstakeRequested {
            contributor,
            asset,
            amount,
            available_at: now + cooldown,
        });
        Ok(())
    }

    pub fn withdraw(ctx: Context<Withdraw>, asset: Asset) -> Result<()> {
        ctx.accounts.config.require_mint(asset, ctx.accounts.mint.key())?;

        let now = Clock::get()?.unix_timestamp;
        let cooldown = ctx.accounts.config.cooldown_seconds;

        let payout = {
            let position = ctx.accounts.stake_account.position(asset);
            require!(
                position.unstake_requested_at > 0,
                StakeError::NoPendingUnstake
            );
            require!(
                logic::cooldown_elapsed(position.unstake_requested_at, now, cooldown),
                StakeError::CooldownActive
            );
            logic::withdrawable(position.unstake_amount, position.amount)
        };
        require!(payout > 0, StakeError::NothingToWithdraw);

        let bump = ctx.accounts.config.bump;
        let signer_seeds: &[&[&[u8]]] = &[&[CONFIG_SEED, &[bump]]];

        token::transfer_checked(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                TransferChecked {
                    from: ctx.accounts.vault.to_account_info(),
                    mint: ctx.accounts.mint.to_account_info(),
                    to: ctx.accounts.contributor_tokens.to_account_info(),
                    authority: ctx.accounts.config.to_account_info(),
                },
                signer_seeds,
            ),
            payout,
            ctx.accounts.mint.decimals,
        )?;

        let contributor = ctx.accounts.stake_account.contributor;
        let position = ctx.accounts.stake_account.position_mut(asset);
        position.amount = position
            .amount
            .checked_sub(payout)
            .ok_or(StakeError::MathOverflow)?;
        position.unstake_amount = 0;
        position.unstake_requested_at = 0;
        let remaining = position.amount;

        ctx.accounts.config.sub_total(asset, payout);

        emit!(Withdrawn {
            contributor,
            asset,
            amount: payout,
            remaining,
        });
        Ok(())
    }

    /// Burn part of a TAP bond. Called by the slash authority when a
    /// contributor's rolling gold-standard accuracy falls below threshold; the
    /// scoring rules live in the backend (tapfarm/scoring.py), which is the
    /// oracle here.
    ///
    /// There is no asset parameter on purpose. SKR is Solana Mobile's token and
    /// confiscating it is not ours to do, so the only slashable stake is TAP -
    /// a property of the interface, not of how carefully it is called.
    ///
    /// Slashed TAP stays in the vault attributed to `slashed_pool`, to be paid
    /// back out as campaign rewards: honest contributors are paid out of
    /// dishonest ones.
    pub fn slash(ctx: Context<Slash>, amount: u64) -> Result<()> {
        require!(amount > 0, StakeError::ZeroAmount);

        let slashed = logic::clamp_slash(ctx.accounts.stake_account.tap.amount, amount);
        require!(slashed > 0, StakeError::NothingToSlash);

        let contributor = ctx.accounts.stake_account.contributor;
        let stake_account = &mut ctx.accounts.stake_account;
        stake_account.tap.amount = stake_account
            .tap
            .amount
            .checked_sub(slashed)
            .ok_or(StakeError::MathOverflow)?;
        let remaining = stake_account.tap.amount;

        let config = &mut ctx.accounts.config;
        config.total_tap_staked = config.total_tap_staked.saturating_sub(slashed);
        config.slashed_pool = config
            .slashed_pool
            .checked_add(slashed)
            .ok_or(StakeError::MathOverflow)?;

        emit!(Slashed {
            contributor,
            amount: slashed,
            remaining,
        });
        Ok(())
    }
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, Default, InitSpace)]
pub struct Position {
    pub amount: u64,
    pub unstake_amount: u64,
    pub unstake_requested_at: i64,
}

#[account]
#[derive(InitSpace)]
pub struct Config {
    pub admin: Pubkey,
    pub slash_authority: Pubkey,
    pub tap_mint: Pubkey,
    pub skr_mint: Pubkey,
    pub min_tap_stake: u64,
    pub min_skr_stake: u64,
    pub cooldown_seconds: i64,
    pub total_tap_staked: u64,
    pub total_skr_staked: u64,
    pub slashed_pool: u64,
    pub bump: u8,
}

impl Config {
    fn mint_for(&self, asset: Asset) -> Pubkey {
        match asset {
            Asset::Tap => self.tap_mint,
            Asset::Skr => self.skr_mint,
        }
    }

    fn require_mint(&self, asset: Asset, mint: Pubkey) -> Result<()> {
        require_keys_eq!(mint, self.mint_for(asset), StakeError::WrongMint);
        Ok(())
    }

    fn add_total(&mut self, asset: Asset, amount: u64) -> Result<()> {
        let total = match asset {
            Asset::Tap => &mut self.total_tap_staked,
            Asset::Skr => &mut self.total_skr_staked,
        };
        *total = total.checked_add(amount).ok_or(StakeError::MathOverflow)?;
        Ok(())
    }

    fn sub_total(&mut self, asset: Asset, amount: u64) {
        let total = match asset {
            Asset::Tap => &mut self.total_tap_staked,
            Asset::Skr => &mut self.total_skr_staked,
        };
        *total = total.saturating_sub(amount);
    }
}

#[account]
#[derive(InitSpace)]
pub struct StakeAccount {
    pub contributor: Pubkey,
    pub tap: Position,
    pub skr: Position,
    pub staked_at: i64,
    pub bump: u8,
}

impl StakeAccount {
    pub fn position(&self, asset: Asset) -> &Position {
        match asset {
            Asset::Tap => &self.tap,
            Asset::Skr => &self.skr,
        }
    }

    pub fn position_mut(&mut self, asset: Asset) -> &mut Position {
        match asset {
            Asset::Tap => &mut self.tap,
            Asset::Skr => &mut self.skr,
        }
    }
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
        seeds = [VAULT_SEED, tap_mint.key().as_ref()],
        bump,
        token::mint = tap_mint,
        token::authority = config,
    )]
    pub tap_vault: Account<'info, TokenAccount>,

    #[account(
        init,
        payer = admin,
        seeds = [VAULT_SEED, skr_mint.key().as_ref()],
        bump,
        token::mint = skr_mint,
        token::authority = config,
    )]
    pub skr_vault: Account<'info, TokenAccount>,

    pub tap_mint: Account<'info, Mint>,
    pub skr_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct Stake<'info> {
    #[account(mut)]
    pub contributor: Signer<'info>,

    #[account(mut, seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,

    #[account(
        init_if_needed,
        payer = contributor,
        space = 8 + StakeAccount::INIT_SPACE,
        seeds = [STAKE_SEED, contributor.key().as_ref()],
        bump,
    )]
    pub stake_account: Account<'info, StakeAccount>,

    #[account(mut, seeds = [VAULT_SEED, mint.key().as_ref()], bump)]
    pub vault: Account<'info, TokenAccount>,

    #[account(
        mut,
        constraint = contributor_tokens.mint == mint.key() @ StakeError::WrongMint,
        constraint = contributor_tokens.owner == contributor.key() @ StakeError::WrongOwner,
    )]
    pub contributor_tokens: Account<'info, TokenAccount>,

    pub mint: Account<'info, Mint>,
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

    #[account(mut, seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,

    #[account(
        mut,
        seeds = [STAKE_SEED, contributor.key().as_ref()],
        bump = stake_account.bump,
        has_one = contributor,
    )]
    pub stake_account: Account<'info, StakeAccount>,

    #[account(mut, seeds = [VAULT_SEED, mint.key().as_ref()], bump)]
    pub vault: Account<'info, TokenAccount>,

    #[account(
        mut,
        constraint = contributor_tokens.mint == mint.key() @ StakeError::WrongMint,
        constraint = contributor_tokens.owner == contributor.key() @ StakeError::WrongOwner,
    )]
    pub contributor_tokens: Account<'info, TokenAccount>,

    pub mint: Account<'info, Mint>,
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
    pub asset: Asset,
    pub amount: u64,
    pub total: u64,
    pub tier: u8,
}

#[event]
pub struct UnstakeRequested {
    pub contributor: Pubkey,
    pub asset: Asset,
    pub amount: u64,
    pub available_at: i64,
}

#[event]
pub struct Withdrawn {
    pub contributor: Pubkey,
    pub asset: Asset,
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
    #[msg("TAP and SKR mints must differ")]
    DuplicateMint,
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
    #[msg("token account or mint does not match the asset")]
    WrongMint,
    #[msg("token account has the wrong owner")]
    WrongOwner,
    #[msg("arithmetic overflow")]
    MathOverflow,
}

#[cfg(test)]
mod tests {
    use super::logic::*;

    const MIN_TAP: u64 = 100_000; // 0.1 TAP
    const MIN_SKR: u64 = 1_000_000; // 1 SKR

    #[test]
    fn unstaked_contributor_is_tier_zero() {
        assert_eq!(tier_for(0, MIN_TAP), 0);
    }

    #[test]
    fn below_minimum_is_still_tier_zero() {
        assert_eq!(tier_for(MIN_TAP - 1, MIN_TAP), 0);
    }

    #[test]
    fn exactly_the_minimum_unlocks_the_staked_tier() {
        assert_eq!(tier_for(MIN_TAP, MIN_TAP), 1);
    }

    #[test]
    fn above_the_minimum_stays_tier_one() {
        assert_eq!(tier_for(MIN_TAP * 50, MIN_TAP), 1);
    }

    #[test]
    fn a_zero_minimum_never_grants_a_tier_for_free() {
        assert_eq!(tier_for(0, 0), 0);
    }

    #[test]
    fn skr_alone_does_not_unlock_the_work_tier() {
        // Holding SKR says nothing about label quality.
        assert_eq!(tier_for(0, MIN_TAP), 0);
        assert!(!referral_eligible(0, MIN_TAP, MIN_SKR * 100, MIN_SKR));
    }

    #[test]
    fn referral_needs_both_stakes() {
        assert!(referral_eligible(MIN_TAP, MIN_TAP, MIN_SKR, MIN_SKR));
    }

    #[test]
    fn referral_denied_without_the_slashable_bond() {
        assert!(!referral_eligible(MIN_TAP - 1, MIN_TAP, MIN_SKR, MIN_SKR));
    }

    #[test]
    fn referral_denied_without_the_skr_stake() {
        assert!(!referral_eligible(MIN_TAP, MIN_TAP, MIN_SKR - 1, MIN_SKR));
    }

    #[test]
    fn referral_denied_when_nothing_is_staked() {
        assert!(!referral_eligible(0, MIN_TAP, 0, MIN_SKR));
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
        assert_eq!(withdrawable(600, 250), 250);
    }

    #[test]
    fn a_full_slash_during_cooldown_leaves_nothing_to_withdraw() {
        assert_eq!(withdrawable(600, 0), 0);
    }
}
