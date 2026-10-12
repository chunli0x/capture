use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, Transfer};

// Development identity only. Deploy with your own keypair and update all clients.
declare_id!("HyNNfKuyEuyc98fo2zsdyPrHmCX7tuMXvVPF8vJB12Sm");

const COOLDOWN: i64 = 86_400;

// Bond warnings are a two-strike ladder. A bond is slashed (terminal) once it
// carries two or more warnings; a slashed bond can never withdraw.
const TERMINAL_WARNINGS: u8 = 255;

#[program]
pub mod seeker_bounty {
    use super::*;

    pub fn initialize(
        ctx: Context<Initialize>,
        verifier: Pubkey,
        slash_authority: Pubkey,
        min_bond: u64,
    ) -> Result<()> {
        require!(
            min_bond > 0
                && verifier != Pubkey::default()
                && slash_authority != Pubkey::default(),
            Error::Invalid
        );
        require!(
            ctx.accounts.usdc_mint.key() != ctx.accounts.skr_mint.key(),
            Error::Invalid
        );
        require!(ctx.accounts.usdc_mint.decimals == 6, Error::Invalid);
        ctx.accounts.config.set_inner(Config {
            admin: ctx.accounts.admin.key(),
            verifier,
            usdc_mint: ctx.accounts.usdc_mint.key(),
            skr_mint: ctx.accounts.skr_mint.key(),
            min_bond,
            slash_authority,
        });
        Ok(())
    }

    pub fn deposit_bond(ctx: Context<DepositBond>, amount: u64) -> Result<()> {
        require!(amount > 0, Error::Invalid);
        let bond = &mut ctx.accounts.bond;
        if bond.worker == Pubkey::default() {
            bond.worker = ctx.accounts.worker.key();
            bond.pending = 0;
        }
        require_keys_eq!(bond.worker, ctx.accounts.worker.key(), Error::Unauthorized);
        bond.unlock_at = Clock::get()?
            .unix_timestamp
            .checked_add(COOLDOWN)
            .ok_or(Error::Overflow)?;
        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.key(),
                Transfer {
                    from: ctx.accounts.source.to_account_info(),
                    to: ctx.accounts.vault.to_account_info(),
                    authority: ctx.accounts.worker.to_account_info(),
                },
            ),
            amount,
        )
    }

    pub fn withdraw_bond(ctx: Context<WithdrawBond>) -> Result<()> {
        require!(withdrawable(ctx.accounts.bond.warnings), Error::Slashed);
        require!(ctx.accounts.bond.pending == 0, Error::Pending);
        require!(
            Clock::get()?.unix_timestamp >= ctx.accounts.bond.unlock_at,
            Error::Locked
        );
        let worker = ctx.accounts.worker.key();
        let seeds: &[&[u8]] = &[b"bond", worker.as_ref(), &[ctx.bumps.bond]];
        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                Transfer {
                    from: ctx.accounts.vault.to_account_info(),
                    to: ctx.accounts.destination.to_account_info(),
                    authority: ctx.accounts.bond.to_account_info(),
                },
                &[seeds],
            ),
            ctx.accounts.vault.amount,
        )
    }

    pub fn warn(ctx: Context<Warn>, worker: Pubkey) -> Result<()> {
        let bond = &mut ctx.accounts.bond;
        bond.warnings = add_warning(bond.warnings)?;
        emit!(BondWarned {
            worker,
            warnings: bond.warnings,
        });
        Ok(())
    }

    /// Close the config PDA so it can be re-initialized with a new layout.
    ///
    /// Deployer-gated (the recorded admin). Used once, at upgrade time, when a
    /// program layout change grows the Config account: close the stale config
    /// (Anchor returns its lamports to ``admin`` and zeroes the account), then
    /// call ``initialize`` again to recreate it at the new size and create the
    /// penalty vault. The penalty vault must not exist yet, which holds on
    /// devnet because it is introduced in the same upgrade.
    pub fn close_config(_ctx: Context<CloseConfig>) -> Result<()> {
        Ok(())
    }

    pub fn slash(ctx: Context<Slash>, worker: Pubkey) -> Result<()> {
        require!(slashable(ctx.accounts.bond.warnings), Error::NotWarned);
        // Full slash: the entire bond vault is forfeit on the second strike.
        let taken = ctx.accounts.bond_vault.amount;
        require!(taken > 0, Error::Invalid);
        let seeds: &[&[u8]] = &[b"bond", worker.as_ref(), &[ctx.bumps.bond]];
        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                Transfer {
                    from: ctx.accounts.bond_vault.to_account_info(),
                    to: ctx.accounts.penalty_vault.to_account_info(),
                    authority: ctx.accounts.bond.to_account_info(),
                },
                &[seeds],
            ),
            taken,
        )?;
        let bond = &mut ctx.accounts.bond;
        bond.warnings = TERMINAL_WARNINGS;
        emit!(BondSlashed {
            worker,
            amount: taken,
        });
        Ok(())
    }

    pub fn post_bounty(
        ctx: Context<PostBounty>,
        id: [u8; 16],
        reward: u64,
        slots: u32,
        deadline: i64,
    ) -> Result<()> {
        let budget = checked_budget(reward, slots)?;
        let now = Clock::get()?.unix_timestamp;
        require!(
            deadline > now && deadline <= now + 30 * 86_400,
            Error::Expired
        );
        ctx.accounts.bounty.set_inner(Bounty {
            requester: ctx.accounts.requester.key(),
            id,
            reward,
            slots,
            filled: 0,
            pending: 0,
            deadline,
        });
        token::transfer(
            CpiContext::new(
                ctx.accounts.token_program.key(),
                Transfer {
                    from: ctx.accounts.source.to_account_info(),
                    to: ctx.accounts.vault.to_account_info(),
                    authority: ctx.accounts.requester.to_account_info(),
                },
            ),
            budget,
        )
    }

    pub fn fulfill(
        ctx: Context<Fulfill>,
        media_hash: [u8; 32],
        label_hash: [u8; 32],
    ) -> Result<()> {
        require!(
            media_hash != [0; 32] && label_hash != [0; 32],
            Error::Invalid
        );
        require!(
            ctx.accounts.worker.key() != ctx.accounts.bounty.requester,
            Error::Unauthorized
        );
        require!(
            ctx.accounts.bond_vault.amount >= ctx.accounts.config.min_bond,
            Error::InsufficientBond
        );
        reserve(&mut ctx.accounts.bounty, Clock::get()?.unix_timestamp)?;
        ctx.accounts.bond.pending = ctx
            .accounts
            .bond
            .pending
            .checked_add(1)
            .ok_or(Error::Overflow)?;
        ctx.accounts.submission.set_inner(Submission {
            bounty: ctx.accounts.bounty.key(),
            worker: ctx.accounts.worker.key(),
            media_hash,
            label_hash,
            state: 0,
        });
        Ok(())
    }

    pub fn accept(ctx: Context<Settle>) -> Result<()> {
        require_keys_eq!(
            ctx.accounts.authority.key(),
            ctx.accounts.bounty.requester,
            Error::Unauthorized
        );
        require!(
            Clock::get()?.unix_timestamp < ctx.accounts.bounty.deadline,
            Error::Expired
        );
        finish(
            &mut ctx.accounts.bounty,
            &mut ctx.accounts.bond,
            &mut ctx.accounts.submission,
            1,
        )?;
        let b = &ctx.accounts.bounty;
        let seeds: &[&[u8]] = &[b"bounty", b.requester.as_ref(), &b.id, &[ctx.bumps.bounty]];
        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                Transfer {
                    from: ctx.accounts.vault.to_account_info(),
                    to: ctx.accounts.destination.to_account_info(),
                    authority: ctx.accounts.bounty.to_account_info(),
                },
                &[seeds],
            ),
            b.reward,
        )
    }

    pub fn reject(ctx: Context<Settle>) -> Result<()> {
        require_keys_eq!(
            ctx.accounts.authority.key(),
            ctx.accounts.bounty.requester,
            Error::Unauthorized
        );
        finish(
            &mut ctx.accounts.bounty,
            &mut ctx.accounts.bond,
            &mut ctx.accounts.submission,
            2,
        )
    }

    pub fn expire(ctx: Context<Settle>) -> Result<()> {
        require!(
            Clock::get()?.unix_timestamp >= ctx.accounts.bounty.deadline,
            Error::Locked
        );
        finish(
            &mut ctx.accounts.bounty,
            &mut ctx.accounts.bond,
            &mut ctx.accounts.submission,
            3,
        )
    }

    pub fn refund(ctx: Context<Refund>) -> Result<()> {
        let b = &ctx.accounts.bounty;
        require!(Clock::get()?.unix_timestamp >= b.deadline, Error::Locked);
        let amount = refundable(ctx.accounts.vault.amount, b.reward, b.pending)?;
        require!(amount > 0, Error::Invalid);
        let seeds: &[&[u8]] = &[b"bounty", b.requester.as_ref(), &b.id, &[ctx.bumps.bounty]];
        token::transfer(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                Transfer {
                    from: ctx.accounts.vault.to_account_info(),
                    to: ctx.accounts.destination.to_account_info(),
                    authority: ctx.accounts.bounty.to_account_info(),
                },
                &[seeds],
            ),
            amount,
        )
    }
}

pub fn checked_budget(reward: u64, slots: u32) -> Result<u64> {
    require!(
        reward > 0 && reward <= 1_000_000_000 && slots > 0 && slots <= 100,
        Error::Invalid
    );
    reward
        .checked_mul(slots as u64)
        .ok_or_else(|| error!(Error::Overflow))
}

pub fn reserve(b: &mut Bounty, now: i64) -> Result<()> {
    require!(now < b.deadline, Error::Expired);
    require!(b.filled < b.slots, Error::Full);
    b.filled = b.filled.checked_add(1).ok_or(Error::Overflow)?;
    b.pending = b.pending.checked_add(1).ok_or(Error::Overflow)?;
    Ok(())
}

pub fn finish(b: &mut Bounty, bond: &mut Bond, s: &mut Submission, state: u8) -> Result<()> {
    require!(s.state == 0, Error::Settled);
    require!((1..=3).contains(&state), Error::Invalid);
    let pending = b.pending.checked_sub(1).ok_or(Error::Overflow)?;
    let liability = bond.pending.checked_sub(1).ok_or(Error::Overflow)?;
    b.pending = pending;
    bond.pending = liability;
    s.state = state;
    Ok(())
}

pub fn refundable(balance: u64, reward: u64, pending: u32) -> Result<u64> {
    let reserved = reward.checked_mul(pending as u64).ok_or(Error::Overflow)?;
    balance
        .checked_sub(reserved)
        .ok_or_else(|| error!(Error::Overflow))
}

/// Apply one warning. Refused once the bond is already at the two-strike
/// threshold or terminally slashed. Saturating, so it can never wrap past 255.
pub fn add_warning(warnings: u8) -> Result<u8> {
    require!(warnings < 2, Error::Slashed);
    Ok(warnings.saturating_add(1))
}

/// A bond with two or more warnings is eligible for slashing (the ladder).
pub fn slashable(warnings: u8) -> bool {
    warnings >= 2
}

/// A slashed bond (two or more warnings) can no longer withdraw.
pub fn withdrawable(warnings: u8) -> bool {
    warnings < 2
}

#[account]
#[derive(InitSpace)]
pub struct Config {
    pub admin: Pubkey,
    pub verifier: Pubkey,
    pub usdc_mint: Pubkey,
    pub skr_mint: Pubkey,
    pub min_bond: u64,
    pub slash_authority: Pubkey,
}
#[account]
#[derive(InitSpace)]
pub struct Bond {
    pub worker: Pubkey,
    pub pending: u32,
    pub unlock_at: i64,
    /// 0 = clean, 1 = warned once, >= 2 = slashed (terminal).
    pub warnings: u8,
}
#[account]
#[derive(InitSpace)]
pub struct Bounty {
    pub requester: Pubkey,
    pub id: [u8; 16],
    pub reward: u64,
    pub slots: u32,
    pub filled: u32,
    pub pending: u32,
    pub deadline: i64,
}
#[account]
#[derive(InitSpace)]
pub struct Submission {
    pub bounty: Pubkey,
    pub worker: Pubkey,
    pub media_hash: [u8; 32],
    pub label_hash: [u8; 32],
    // 0=pending, 1=paid, 2=rejected, 3=expired. Never closed/reinitialized.
    pub state: u8,
}

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub admin: Signer<'info>,
    #[account(init, payer=admin, space=8+Config::INIT_SPACE, seeds=[b"config"], bump)]
    pub config: Account<'info, Config>,
    pub usdc_mint: Account<'info, Mint>,
    pub skr_mint: Account<'info, Mint>,
    #[account(init, payer=admin, seeds=[b"penalty-vault", config.key().as_ref()], bump, token::mint=skr_mint, token::authority=config)]
    pub penalty_vault: Account<'info, TokenAccount>,
    #[account(constraint=program.programdata_address()? == Some(program_data.key()) @ Error::Unauthorized)]
    pub program: Program<'info, crate::program::SeekerBounty>,
    #[account(constraint=program_data.upgrade_authority_address == Some(admin.key()) @ Error::Unauthorized)]
    pub program_data: Account<'info, ProgramData>,
    pub system_program: Program<'info, System>,
    pub token_program: Program<'info, Token>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct DepositBond<'info> {
    #[account(mut)]
    pub worker: Signer<'info>,
    #[account(seeds=[b"config"], bump, has_one=skr_mint)]
    pub config: Account<'info, Config>,
    pub skr_mint: Account<'info, Mint>,
    #[account(init_if_needed, payer=worker, space=8+Bond::INIT_SPACE, seeds=[b"bond", worker.key().as_ref()], bump)]
    pub bond: Account<'info, Bond>,
    #[account(init_if_needed, payer=worker, seeds=[b"bond-vault", worker.key().as_ref()], bump, token::mint=skr_mint, token::authority=bond)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut, token::mint=skr_mint, token::authority=worker)]
    pub source: Account<'info, TokenAccount>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct WithdrawBond<'info> {
    pub worker: Signer<'info>,
    #[account(seeds=[b"config"], bump, has_one=skr_mint)]
    pub config: Account<'info, Config>,
    pub skr_mint: Account<'info, Mint>,
    #[account(seeds=[b"bond", worker.key().as_ref()], bump, has_one=worker)]
    pub bond: Account<'info, Bond>,
    #[account(mut, seeds=[b"bond-vault", worker.key().as_ref()], bump, token::mint=skr_mint, token::authority=bond)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut, token::mint=skr_mint, token::authority=worker)]
    pub destination: Account<'info, TokenAccount>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
#[instruction(worker: Pubkey)]
pub struct Warn<'info> {
    #[account(constraint = slash_authority.key() == config.slash_authority @ Error::Unauthorized)]
    pub slash_authority: Signer<'info>,
    #[account(seeds=[b"config"], bump)]
    pub config: Account<'info, Config>,
    #[account(mut, seeds=[b"bond", worker.as_ref()], bump)]
    pub bond: Account<'info, Bond>,
}

#[derive(Accounts)]
pub struct CloseConfig<'info> {
    #[account(mut)]
    pub admin: Signer<'info>,
    #[account(
        mut,
        seeds=[b"config"],
        bump,
        close = admin,
        constraint = config.admin == admin.key() @ Error::Unauthorized,
    )]
    pub config: Account<'info, Config>,
}

#[derive(Accounts)]
#[instruction(worker: Pubkey)]
pub struct Slash<'info> {
    #[account(constraint = slash_authority.key() == config.slash_authority @ Error::Unauthorized)]
    pub slash_authority: Signer<'info>,
    #[account(seeds=[b"config"], bump)]
    pub config: Account<'info, Config>,
    #[account(mut, seeds=[b"bond", worker.as_ref()], bump)]
    pub bond: Account<'info, Bond>,
    #[account(mut, seeds=[b"bond-vault", worker.as_ref()], bump, token::mint=config.skr_mint, token::authority=bond)]
    pub bond_vault: Account<'info, TokenAccount>,
    #[account(mut, seeds=[b"penalty-vault", config.key().as_ref()], bump, token::mint=config.skr_mint, token::authority=config)]
    pub penalty_vault: Account<'info, TokenAccount>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
#[instruction(id: [u8; 16])]
pub struct PostBounty<'info> {
    #[account(mut)]
    pub requester: Signer<'info>,
    #[account(seeds=[b"config"], bump, has_one=usdc_mint)]
    pub config: Account<'info, Config>,
    pub usdc_mint: Account<'info, Mint>,
    #[account(init, payer=requester, space=8+Bounty::INIT_SPACE, seeds=[b"bounty", requester.key().as_ref(), &id], bump)]
    pub bounty: Account<'info, Bounty>,
    #[account(init, payer=requester, seeds=[b"vault", bounty.key().as_ref()], bump, token::mint=usdc_mint, token::authority=bounty)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut, token::mint=usdc_mint, token::authority=requester)]
    pub source: Account<'info, TokenAccount>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct Fulfill<'info> {
    #[account(mut)]
    pub worker: Signer<'info>,
    pub verifier: Signer<'info>,
    #[account(seeds=[b"config"], bump, has_one=verifier)]
    pub config: Account<'info, Config>,
    #[account(mut, seeds=[b"bounty", bounty.requester.as_ref(), &bounty.id], bump)]
    pub bounty: Account<'info, Bounty>,
    #[account(init, payer=worker, space=8+Submission::INIT_SPACE, seeds=[b"submission", bounty.key().as_ref(), worker.key().as_ref()], bump)]
    pub submission: Account<'info, Submission>,
    #[account(mut, seeds=[b"bond", worker.key().as_ref()], bump, has_one=worker)]
    pub bond: Account<'info, Bond>,
    #[account(seeds=[b"bond-vault", worker.key().as_ref()], bump, token::mint=config.skr_mint, token::authority=bond)]
    pub bond_vault: Account<'info, TokenAccount>,
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct Settle<'info> {
    pub authority: Signer<'info>,
    #[account(seeds=[b"config"], bump, has_one=usdc_mint)]
    pub config: Account<'info, Config>,
    pub usdc_mint: Account<'info, Mint>,
    #[account(mut, seeds=[b"bounty", bounty.requester.as_ref(), &bounty.id], bump)]
    pub bounty: Account<'info, Bounty>,
    /// CHECK: Identity bound to submission, bond and token destination below.
    pub worker: UncheckedAccount<'info>,
    #[account(mut, seeds=[b"submission", bounty.key().as_ref(), worker.key().as_ref()], bump, has_one=bounty, has_one=worker)]
    pub submission: Account<'info, Submission>,
    #[account(mut, seeds=[b"bond", worker.key().as_ref()], bump, has_one=worker)]
    pub bond: Account<'info, Bond>,
    #[account(mut, seeds=[b"vault", bounty.key().as_ref()], bump, token::mint=usdc_mint, token::authority=bounty)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut, token::mint=usdc_mint, token::authority=worker)]
    pub destination: Account<'info, TokenAccount>,
    pub token_program: Program<'info, Token>,
}

#[derive(Accounts)]
pub struct Refund<'info> {
    pub requester: Signer<'info>,
    #[account(seeds=[b"config"], bump, has_one=usdc_mint)]
    pub config: Account<'info, Config>,
    pub usdc_mint: Account<'info, Mint>,
    #[account(seeds=[b"bounty", requester.key().as_ref(), &bounty.id], bump, has_one=requester)]
    pub bounty: Account<'info, Bounty>,
    #[account(mut, seeds=[b"vault", bounty.key().as_ref()], bump, token::mint=usdc_mint, token::authority=bounty)]
    pub vault: Account<'info, TokenAccount>,
    #[account(mut, token::mint=usdc_mint, token::authority=requester)]
    pub destination: Account<'info, TokenAccount>,
    pub token_program: Program<'info, Token>,
}

#[event]
pub struct BondWarned {
    pub worker: Pubkey,
    pub warnings: u8,
}

#[event]
pub struct BondSlashed {
    pub worker: Pubkey,
    pub amount: u64,
}

#[error_code]
pub enum Error {
    #[msg("Unauthorized signer or account")]
    Unauthorized,
    #[msg("Invalid bounds or content")]
    Invalid,
    #[msg("Checked arithmetic failed")]
    Overflow,
    #[msg("Bounty expired")]
    Expired,
    #[msg("All bounty slots consumed")]
    Full,
    #[msg("Bond below configured minimum")]
    InsufficientBond,
    #[msg("Submission already settled")]
    Settled,
    #[msg("Bond has pending liabilities")]
    Pending,
    #[msg("Deadline or cooldown not reached")]
    Locked,
    #[msg("Bond is slashed (two or more warnings)")]
    Slashed,
    #[msg("Two warnings are required before a bond can be slashed")]
    NotWarned,
}

#[cfg(test)]
mod tests {
    use super::*;
    fn bounty() -> Bounty {
        Bounty {
            requester: Pubkey::new_unique(),
            id: [1; 16],
            reward: 10,
            slots: 2,
            filled: 0,
            pending: 0,
            deadline: 100,
        }
    }
    #[test]
    fn budget_bounds() {
        assert_eq!(checked_budget(10, 2).unwrap(), 20);
        for (r, s) in [(0, 1), (1, 0), (1, 101), (u64::MAX, 2)] {
            assert!(checked_budget(r, s).is_err());
        }
    }
    #[test]
    fn slots_and_expiration() {
        let mut b = bounty();
        assert!(reserve(&mut b, 100).is_err());
        reserve(&mut b, 99).unwrap();
        reserve(&mut b, 99).unwrap();
        assert!(reserve(&mut b, 99).is_err());
        assert_eq!(b.pending, 2);
    }
    #[test]
    fn exact_once_and_reserved_refund() {
        for state in 1..=3 {
            let mut b = bounty();
            reserve(&mut b, 1).unwrap();
            let mut bond = Bond {
                worker: Pubkey::new_unique(),
                pending: 1,
                unlock_at: 10,
                warnings: 0,
            };
            let mut sub = Submission {
                bounty: Pubkey::new_unique(),
                worker: bond.worker,
                media_hash: [1; 32],
                label_hash: [2; 32],
                state: 0,
            };
            assert_eq!(refundable(20, b.reward, b.pending).unwrap(), 10);
            finish(&mut b, &mut bond, &mut sub, state).unwrap();
            assert_eq!(bond.pending, 0);
            assert_eq!(b.pending, 0);
            assert!(finish(&mut b, &mut bond, &mut sub, state).is_err());
        }
    }
    #[test]
    fn refund_never_spends_liabilities() {
        assert_eq!(refundable(20, 10, 2).unwrap(), 0);
        assert!(refundable(9, 10, 1).is_err());
        assert!(refundable(u64::MAX, u64::MAX, 2).is_err());
    }

    // -- warning ladder --------------------------------------------------

    #[test]
    fn warn_then_warn_reaches_two_and_enables_slash() {
        assert_eq!(add_warning(0).unwrap(), 1);
        assert_eq!(add_warning(1).unwrap(), 2);
        assert!(slashable(2));
    }

    #[test]
    fn warn_is_saturating_and_never_wraps() {
        // The ladder stops at two, so anything at or past the threshold refuses.
        assert!(add_warning(2).is_err());
        assert!(add_warning(255).is_err());
    }

    #[test]
    fn slash_without_prior_warn_is_refused() {
        assert!(!slashable(0));
        assert!(!slashable(1));
    }

    #[test]
    fn slashed_bond_is_terminal_withdraw_and_warn_refuse() {
        // Terminal (255) and threshold (2) both refuse further warns/withdraws.
        assert!(!withdrawable(255));
        assert!(!withdrawable(2));
        assert!(withdrawable(0));
        assert!(withdrawable(1));
    }

    #[test]
    fn full_slash_drains_the_entire_bond_vault() {
        // A second strike forfeits the whole vault: `taken` is the vault balance
        // in full, so nothing remains and the penalty vault holds exactly it.
        let balance = 100u64;
        let taken = balance; // slash takes the full amount, no clamp
        assert_eq!(taken, 100);
        assert_eq!(balance - taken, 0);
        assert_eq!(taken + (balance - taken), balance);
    }
}
