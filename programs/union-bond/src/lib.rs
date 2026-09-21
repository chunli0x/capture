//! Union bond - the part of an attestation that has money behind it.
//!
//! The credential itself is issued by the Solana Attestation Service, which
//! already enforces that a verifier we authorised signed it. What SAS has no
//! concept of is a **stake**: it cannot escrow a token, it cannot slash one,
//! and its attestations cannot be updated, so a status can never move. That is
//! what this program is for, and it is deliberately nothing more.
//!
//! The claim Union sells is not "someone attested this". It is "someone
//! attested this with money at risk". This program is where the money is.
//!
//! ```text
//!   SAS attestation ──nonce──► bond PDA [human, task_id]  ◄── this program
//!     (credential)                 │
//!                                  ├─ HUMAN escrowed in the vault
//!                                  ├─ liveness_proof_hash (spent once, ever)
//!                                  └─ status: Attested → Challenged → Slashed
//! ```
//!
//! ## Two signers, and why the human is one of them
//!
//! `post_bond` requires **both** the verifier and the human to sign. SAS's own
//! `create_attestation` takes only an authorized signer, so on SAS alone a
//! credential can be minted about somebody who never touched it. Requiring the
//! human here is what makes them a party to the claim rather than its subject,
//! and it is the only place the liveness-proof hash is bound to a wallet by a
//! signature rather than by assertion.
//!
//! ## HUMAN is the bond; SKR is never touched
//!
//! This program knows one mint. There is no asset parameter on `slash` and no
//! second vault, so "SKR is never slashed" is a fact about the account set
//! rather than a promise about future conduct - the same structural argument
//! `tapfarm-stake` makes by giving `slash` no way to name the SKR vault.
//!
//! ## What is not wired
//!
//! `slash` and `challenge` are implemented and tested, and no backend calls
//! them. Enforcement is v2. The honest sentence for the demo is that the bond
//! is staked and the attestation is minted; nothing here says a false
//! attestation has ever actually been punished.

use anchor_lang::prelude::*;
use anchor_spl::token::{self, Mint, Token, TokenAccount, TransferChecked};

declare_id!("BondDfbRr6dZ4TYr6yBSAqWnJb1zpCPtkTqTH1HNMz6a");

pub const CONFIG_SEED: &[u8] = b"config";
pub const BOND_SEED: &[u8] = b"bond";
pub const VAULT_SEED: &[u8] = b"vault";
pub const LIVENESS_SEED: &[u8] = b"liveness";

/// Longest `task_id` accepted.
///
/// A PDA seed cannot exceed 32 bytes, and the task ids this system issues
/// ("qualify-0007", "live-0042") are far shorter. Enforced rather than assumed
/// so a longer id fails here with a named error instead of as an opaque
/// `MaxSeedLengthExceeded` from the runtime.
pub const MAX_TASK_ID_LEN: usize = 32;

/// The only key permitted to call `initialize`.
///
/// `tapfarm-stake::initialize` let any signer become admin, which is
/// front-runnable on deploy and unrecoverable. Hardcoding the deployer closes
/// that: a race to call `initialize` first is simply rejected.
///
/// This is the devnet treasury created by `scripts/bootstrap_devnet.sh`.
/// **It must be changed before any mainnet deploy**, and the upgrade authority
/// moved to a multisig or revoked.
pub const DEPLOYER: Pubkey = pubkey!("EYWceKawCcE7XuxSBF7mrh19GDqVFUTCURdje2e2aB16");

/// Where a bond is in its life.
///
/// `Challenged` exists now even though nothing disputes a bond yet. The
/// security review asked for the account layout not to foreclose an on-chain
/// dispute path, and adding a variant later would mean migrating every
/// existing account.
#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, Debug, InitSpace)]
pub enum BondStatus {
    Attested,
    Challenged,
    Slashed,
    Released,
}

/// Decision logic, free of Anchor types so it runs under a plain `cargo test`
/// on the host rather than only inside a validator.
pub mod logic {
    use super::BondStatus;

    /// How much of a bond a slash actually takes.
    ///
    /// Clamped rather than rejected: a slash for more than is staked should
    /// take everything, not fail and leave the bond intact.
    pub fn clamp_slash(bonded: u64, requested: u64) -> u64 {
        if requested > bonded {
            bonded
        } else {
            requested
        }
    }

    /// Whether a bond may be released back to the human.
    ///
    /// Only an unchallenged bond, and only once the window has passed. A bond
    /// returnable on demand is not collateral: the holder would withdraw the
    /// moment their work was questioned, which is the exact moment it needs to
    /// still be there.
    pub fn releasable(
        status: BondStatus,
        attested_at: i64,
        now: i64,
        challenge_window_seconds: i64,
    ) -> bool {
        matches!(status, BondStatus::Attested)
            && now.saturating_sub(attested_at) >= challenge_window_seconds
    }

    /// Legal status moves. Everything else is rejected.
    ///
    /// Written as a table rather than scattered `require!`s so the whole
    /// lifecycle can be read, and tested, in one place.
    pub fn may_transition(from: BondStatus, to: BondStatus) -> bool {
        matches!(
            (from, to),
            (BondStatus::Attested, BondStatus::Challenged)
                | (BondStatus::Attested, BondStatus::Released)
                | (BondStatus::Challenged, BondStatus::Slashed)
                | (BondStatus::Challenged, BondStatus::Attested)
        )
    }

    /// A task id has to fit in a PDA seed.
    pub fn task_id_ok(task_id: &str, max_len: usize) -> bool {
        !task_id.is_empty() && task_id.len() <= max_len
    }
}

#[program]
pub mod union_bond {
    use super::*;

    /// One-time setup. Gated to [`DEPLOYER`].
    pub fn initialize(
        ctx: Context<Initialize>,
        verifier: Pubkey,
        slash_authority: Pubkey,
        min_bond: u64,
        challenge_window_seconds: i64,
    ) -> Result<()> {
        require_keys_eq!(
            ctx.accounts.admin.key(),
            DEPLOYER,
            BondError::NotDeployer
        );
        require!(challenge_window_seconds >= 0, BondError::InvalidWindow);

        let config = &mut ctx.accounts.config;
        config.admin = ctx.accounts.admin.key();
        config.verifier = verifier;
        config.slash_authority = slash_authority;
        config.human_mint = ctx.accounts.human_mint.key();
        config.min_bond = min_bond;
        config.challenge_window_seconds = challenge_window_seconds;
        config.total_bonded = 0;
        config.total_slashed = 0;
        config.bump = ctx.bumps.config;
        Ok(())
    }

    /// Rotate the verifier and slash authority. Admin only.
    ///
    /// The review's HIGH finding: a single non-rotatable authority means a
    /// compromised key ends the system. Passing `None` leaves a role unchanged
    /// so rotating one does not require restating the other.
    pub fn update_authorities(
        ctx: Context<UpdateAuthorities>,
        verifier: Option<Pubkey>,
        slash_authority: Option<Pubkey>,
        admin: Option<Pubkey>,
    ) -> Result<()> {
        let config = &mut ctx.accounts.config;
        if let Some(key) = verifier {
            config.verifier = key;
        }
        if let Some(key) = slash_authority {
            config.slash_authority = key;
        }
        if let Some(key) = admin {
            require_keys_neq!(key, Pubkey::default(), BondError::InvalidAuthority);
            config.admin = key;
        }
        emit!(AuthoritiesUpdated {
            admin: config.admin,
            verifier: config.verifier,
            slash_authority: config.slash_authority,
        });
        Ok(())
    }

    /// Escrow a bond behind one attestation. Both the human and the verifier sign.
    ///
    /// The `liveness_receipt` account is the replay guard: it is `init`ed at a
    /// PDA derived from the liveness-proof hash, so a second attempt to spend
    /// the same hash fails at account creation rather than needing a lookup.
    pub fn post_bond(
        ctx: Context<PostBond>,
        task_id: String,
        liveness_proof_hash: [u8; 32],
        amount: u64,
    ) -> Result<()> {
        require!(
            logic::task_id_ok(&task_id, MAX_TASK_ID_LEN),
            BondError::TaskIdTooLong
        );
        require!(amount > 0, BondError::ZeroAmount);
        require!(
            amount >= ctx.accounts.config.min_bond,
            BondError::BondTooSmall
        );
        require!(
            liveness_proof_hash != [0u8; 32],
            BondError::EmptyLivenessHash
        );

        token::transfer_checked(
            CpiContext::new(
                ctx.accounts.token_program.key(),
                TransferChecked {
                    from: ctx.accounts.human_tokens.to_account_info(),
                    mint: ctx.accounts.human_mint.to_account_info(),
                    to: ctx.accounts.vault.to_account_info(),
                    authority: ctx.accounts.human.to_account_info(),
                },
            ),
            amount,
            ctx.accounts.human_mint.decimals,
        )?;

        let now = Clock::get()?.unix_timestamp;
        let bond = &mut ctx.accounts.bond;
        bond.human = ctx.accounts.human.key();
        bond.task_id = task_id.clone();
        bond.liveness_proof_hash = liveness_proof_hash;
        bond.amount = amount;
        bond.status = BondStatus::Attested;
        bond.evidence_hash = [0u8; 32];
        bond.attested_at = now;
        bond.verifier = ctx.accounts.verifier.key();
        bond.bump = ctx.bumps.bond;

        let receipt = &mut ctx.accounts.liveness_receipt;
        receipt.bond = ctx.accounts.bond.key();
        receipt.bump = ctx.bumps.liveness_receipt;

        let config = &mut ctx.accounts.config;
        config.total_bonded = config
            .total_bonded
            .checked_add(amount)
            .ok_or(BondError::MathOverflow)?;

        emit!(BondPosted {
            human: ctx.accounts.human.key(),
            task_id,
            amount,
            verifier: ctx.accounts.verifier.key(),
            attested_at: now,
        });
        Ok(())
    }

    /// Open a dispute against a bond, committing to evidence held off-chain.
    ///
    /// Implemented and tested; nothing in the backend calls it. The evidence
    /// hash is a commitment, not the evidence: what it points at is not this
    /// program's business, and storing the material itself on-chain would be
    /// both expensive and, for anything about a person, wrong.
    pub fn challenge(ctx: Context<Challenge>, evidence_hash: [u8; 32]) -> Result<()> {
        require!(evidence_hash != [0u8; 32], BondError::EmptyEvidence);
        let bond = &mut ctx.accounts.bond;
        require!(
            logic::may_transition(bond.status, BondStatus::Challenged),
            BondError::IllegalTransition
        );
        bond.status = BondStatus::Challenged;
        bond.evidence_hash = evidence_hash;
        emit!(BondChallenged {
            human: bond.human,
            task_id: bond.task_id.clone(),
        });
        Ok(())
    }

    /// Dismiss a challenge, returning the bond to good standing.
    ///
    /// A dispute path with no way back would make a challenge a punishment in
    /// itself, which is an obvious griefing vector.
    pub fn dismiss_challenge(ctx: Context<Challenge>) -> Result<()> {
        let bond = &mut ctx.accounts.bond;
        require!(
            logic::may_transition(bond.status, BondStatus::Attested),
            BondError::IllegalTransition
        );
        bond.status = BondStatus::Attested;
        bond.evidence_hash = [0u8; 32];
        Ok(())
    }

    /// Take a challenged bond. Only HUMAN can be taken; there is no other vault.
    ///
    /// Only from `Challenged`: slashing straight from `Attested` would make
    /// the dispute path decorative, and the whole argument for the bond being
    /// fair rests on there having been a chance to answer.
    pub fn slash(ctx: Context<Slash>, amount: u64) -> Result<()> {
        require!(amount > 0, BondError::ZeroAmount);
        let bond = &ctx.accounts.bond;
        require!(
            logic::may_transition(bond.status, BondStatus::Slashed),
            BondError::IllegalTransition
        );

        let taken = logic::clamp_slash(bond.amount, amount);
        require!(taken > 0, BondError::NothingToSlash);

        let bond = &mut ctx.accounts.bond;
        bond.amount = bond
            .amount
            .checked_sub(taken)
            .ok_or(BondError::MathOverflow)?;
        bond.status = BondStatus::Slashed;

        let config = &mut ctx.accounts.config;
        // checked, not saturating: a total that silently floors at zero hides
        // an accounting bug instead of surfacing it. The review flagged the
        // saturating_sub in tapfarm-stake for the same reason.
        config.total_bonded = config
            .total_bonded
            .checked_sub(taken)
            .ok_or(BondError::MathOverflow)?;
        config.total_slashed = config
            .total_slashed
            .checked_add(taken)
            .ok_or(BondError::MathOverflow)?;

        emit!(BondSlashed {
            human: ctx.accounts.bond.human,
            amount: taken,
            remaining: ctx.accounts.bond.amount,
        });
        Ok(())
    }

    /// Return an unchallenged bond once the challenge window has passed.
    pub fn release(ctx: Context<Release>) -> Result<()> {
        let now = Clock::get()?.unix_timestamp;
        let config_window = ctx.accounts.config.challenge_window_seconds;
        let bond_status = ctx.accounts.bond.status;
        let attested_at = ctx.accounts.bond.attested_at;

        require!(
            logic::releasable(bond_status, attested_at, now, config_window),
            BondError::NotReleasable
        );
        let amount = ctx.accounts.bond.amount;
        require!(amount > 0, BondError::ZeroAmount);

        let human_mint = ctx.accounts.config.human_mint;
        let bump = ctx.accounts.config.bump;
        let signer_seeds: &[&[&[u8]]] = &[&[CONFIG_SEED, human_mint.as_ref(), &[bump]]];

        token::transfer_checked(
            CpiContext::new_with_signer(
                ctx.accounts.token_program.key(),
                TransferChecked {
                    from: ctx.accounts.vault.to_account_info(),
                    mint: ctx.accounts.human_mint.to_account_info(),
                    to: ctx.accounts.human_tokens.to_account_info(),
                    authority: ctx.accounts.config.to_account_info(),
                },
                signer_seeds,
            ),
            amount,
            ctx.accounts.human_mint.decimals,
        )?;

        let bond = &mut ctx.accounts.bond;
        bond.amount = 0;
        bond.status = BondStatus::Released;

        let config = &mut ctx.accounts.config;
        config.total_bonded = config
            .total_bonded
            .checked_sub(amount)
            .ok_or(BondError::MathOverflow)?;

        emit!(BondReleased {
            human: ctx.accounts.bond.human,
            amount,
        });
        Ok(())
    }
}

// --- accounts ---------------------------------------------------------------

#[account]
#[derive(InitSpace)]
pub struct Config {
    pub admin: Pubkey,
    /// The key that must co-sign every `post_bond`. Mirrors the authorized
    /// signer on our SAS credential; rotate both together.
    pub verifier: Pubkey,
    pub slash_authority: Pubkey,
    pub human_mint: Pubkey,
    pub min_bond: u64,
    pub challenge_window_seconds: i64,
    pub total_bonded: u64,
    /// Cumulative slashed. Bookkeeping only - there is no redistribution
    /// instruction, and saying so here keeps anyone from reading it as a
    /// claimable pool, which is what the review found in `tapfarm-stake`.
    pub total_slashed: u64,
    pub bump: u8,
}

#[account]
#[derive(InitSpace)]
pub struct Bond {
    pub human: Pubkey,
    #[max_len(32)]
    pub task_id: String,
    /// Bound into the payload the human signed. Spendable exactly once,
    /// enforced by `LivenessReceipt` rather than by a scan.
    pub liveness_proof_hash: [u8; 32],
    pub amount: u64,
    pub status: BondStatus,
    /// Commitment to off-chain evidence for a challenge. Zero until disputed.
    pub evidence_hash: [u8; 32],
    pub attested_at: i64,
    pub verifier: Pubkey,
    pub bump: u8,
}

/// Proof that one liveness hash has been spent.
///
/// Exists only to occupy its PDA: a second `post_bond` with the same hash
/// collides with an account that already exists, so replay is refused by the
/// runtime rather than by logic that could be forgotten.
#[account]
#[derive(InitSpace)]
pub struct LivenessReceipt {
    pub bond: Pubkey,
    pub bump: u8,
}

// --- contexts ---------------------------------------------------------------

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub admin: Signer<'info>,
    #[account(
        init,
        payer = admin,
        space = 8 + Config::INIT_SPACE,
        seeds = [CONFIG_SEED, human_mint.key().as_ref()],
        bump
    )]
    pub config: Account<'info, Config>,
    #[account(
        init,
        payer = admin,
        seeds = [VAULT_SEED, human_mint.key().as_ref()],
        bump,
        token::mint = human_mint,
        token::authority = config,
    )]
    pub vault: Account<'info, TokenAccount>,
    pub human_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct UpdateAuthorities<'info> {
    pub admin: Signer<'info>,
    #[account(
        mut,
        seeds = [CONFIG_SEED, config.human_mint.as_ref()],
        bump = config.bump,
        has_one = admin @ BondError::NotAdmin,
    )]
    pub config: Account<'info, Config>,
}

#[derive(Accounts)]
#[instruction(task_id: String, liveness_proof_hash: [u8; 32])]
pub struct PostBond<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,
    /// The subject of the attestation. Signs, so the claim is something they
    /// made rather than something made about them.
    pub human: Signer<'info>,
    /// Must be the verifier recorded at `initialize` or rotated since.
    #[account(constraint = verifier.key() == config.verifier @ BondError::NotVerifier)]
    pub verifier: Signer<'info>,

    #[account(
        mut,
        seeds = [CONFIG_SEED, config.human_mint.as_ref()],
        bump = config.bump,
    )]
    pub config: Account<'info, Config>,

    #[account(
        init,
        payer = payer,
        space = 8 + Bond::INIT_SPACE,
        seeds = [BOND_SEED, human.key().as_ref(), task_id.as_bytes()],
        bump
    )]
    pub bond: Account<'info, Bond>,

    #[account(
        init,
        payer = payer,
        space = 8 + LivenessReceipt::INIT_SPACE,
        seeds = [LIVENESS_SEED, liveness_proof_hash.as_ref()],
        bump
    )]
    pub liveness_receipt: Account<'info, LivenessReceipt>,

    #[account(
        mut,
        seeds = [VAULT_SEED, config.human_mint.as_ref()],
        bump,
        constraint = vault.mint == config.human_mint @ BondError::WrongMint,
    )]
    pub vault: Account<'info, TokenAccount>,
    #[account(
        mut,
        constraint = human_tokens.mint == config.human_mint @ BondError::WrongMint,
        constraint = human_tokens.owner == human.key() @ BondError::WrongOwner,
    )]
    pub human_tokens: Account<'info, TokenAccount>,
    #[account(constraint = human_mint.key() == config.human_mint @ BondError::WrongMint)]
    pub human_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(Accounts)]
pub struct Challenge<'info> {
    #[account(constraint = authority.key() == config.slash_authority @ BondError::NotSlashAuthority)]
    pub authority: Signer<'info>,
    #[account(
        seeds = [CONFIG_SEED, config.human_mint.as_ref()],
        bump = config.bump,
    )]
    pub config: Account<'info, Config>,
    #[account(
        mut,
        seeds = [BOND_SEED, bond.human.as_ref(), bond.task_id.as_bytes()],
        bump = bond.bump,
    )]
    pub bond: Account<'info, Bond>,
}

#[derive(Accounts)]
pub struct Slash<'info> {
    #[account(constraint = authority.key() == config.slash_authority @ BondError::NotSlashAuthority)]
    pub authority: Signer<'info>,
    #[account(
        mut,
        seeds = [CONFIG_SEED, config.human_mint.as_ref()],
        bump = config.bump,
    )]
    pub config: Account<'info, Config>,
    #[account(
        mut,
        seeds = [BOND_SEED, bond.human.as_ref(), bond.task_id.as_bytes()],
        bump = bond.bump,
    )]
    pub bond: Account<'info, Bond>,
}

#[derive(Accounts)]
pub struct Release<'info> {
    pub human: Signer<'info>,
    #[account(
        mut,
        seeds = [CONFIG_SEED, config.human_mint.as_ref()],
        bump = config.bump,
    )]
    pub config: Account<'info, Config>,
    #[account(
        mut,
        seeds = [BOND_SEED, human.key().as_ref(), bond.task_id.as_bytes()],
        bump = bond.bump,
        constraint = bond.human == human.key() @ BondError::WrongOwner,
    )]
    pub bond: Account<'info, Bond>,
    #[account(
        mut,
        seeds = [VAULT_SEED, config.human_mint.as_ref()],
        bump,
    )]
    pub vault: Account<'info, TokenAccount>,
    #[account(
        mut,
        constraint = human_tokens.mint == config.human_mint @ BondError::WrongMint,
        constraint = human_tokens.owner == human.key() @ BondError::WrongOwner,
    )]
    pub human_tokens: Account<'info, TokenAccount>,
    #[account(constraint = human_mint.key() == config.human_mint @ BondError::WrongMint)]
    pub human_mint: Account<'info, Mint>,
    pub token_program: Program<'info, Token>,
}

// --- events -----------------------------------------------------------------

#[event]
pub struct BondPosted {
    pub human: Pubkey,
    pub task_id: String,
    pub amount: u64,
    pub verifier: Pubkey,
    pub attested_at: i64,
}

#[event]
pub struct BondChallenged {
    pub human: Pubkey,
    pub task_id: String,
}

#[event]
pub struct BondSlashed {
    pub human: Pubkey,
    pub amount: u64,
    pub remaining: u64,
}

#[event]
pub struct BondReleased {
    pub human: Pubkey,
    pub amount: u64,
}

#[event]
pub struct AuthoritiesUpdated {
    pub admin: Pubkey,
    pub verifier: Pubkey,
    pub slash_authority: Pubkey,
}

#[error_code]
pub enum BondError {
    #[msg("initialize is restricted to the deployer key")]
    NotDeployer,
    #[msg("only the admin may rotate authorities")]
    NotAdmin,
    #[msg("the verifier did not sign")]
    NotVerifier,
    #[msg("only the slash authority may do this")]
    NotSlashAuthority,
    #[msg("amount must be greater than zero")]
    ZeroAmount,
    #[msg("bond is below the configured minimum")]
    BondTooSmall,
    #[msg("task id must be 1..=32 bytes")]
    TaskIdTooLong,
    #[msg("liveness proof hash must not be empty")]
    EmptyLivenessHash,
    #[msg("evidence hash must not be empty")]
    EmptyEvidence,
    #[msg("that status change is not allowed")]
    IllegalTransition,
    #[msg("nothing left to slash")]
    NothingToSlash,
    #[msg("bond is challenged or still inside the challenge window")]
    NotReleasable,
    #[msg("account does not use the configured HUMAN mint")]
    WrongMint,
    #[msg("token account is not owned by this human")]
    WrongOwner,
    #[msg("authority must not be the default pubkey")]
    InvalidAuthority,
    #[msg("challenge window must not be negative")]
    InvalidWindow,
    #[msg("arithmetic overflow")]
    MathOverflow,
}

#[cfg(test)]
mod tests {
    use super::logic::*;
    use super::BondStatus;
    use super::MAX_TASK_ID_LEN;

    // -- slash clamping --------------------------------------------------

    #[test]
    fn slashing_more_than_is_bonded_takes_everything() {
        assert_eq!(clamp_slash(100, 250), 100);
    }

    #[test]
    fn slashing_less_takes_exactly_that() {
        assert_eq!(clamp_slash(100, 40), 40);
    }

    #[test]
    fn slashing_an_empty_bond_takes_nothing() {
        assert_eq!(clamp_slash(0, 40), 0);
    }

    // -- the lifecycle ---------------------------------------------------

    #[test]
    fn a_bond_can_be_challenged_then_slashed() {
        assert!(may_transition(BondStatus::Attested, BondStatus::Challenged));
        assert!(may_transition(BondStatus::Challenged, BondStatus::Slashed));
    }

    #[test]
    fn slashing_straight_from_attested_is_refused() {
        // Otherwise the dispute path is decorative, and the fairness argument
        // for the bond disappears with it.
        assert!(!may_transition(BondStatus::Attested, BondStatus::Slashed));
    }

    #[test]
    fn a_challenge_can_be_dismissed() {
        // A challenge with no way back is a punishment in itself.
        assert!(may_transition(BondStatus::Challenged, BondStatus::Attested));
    }

    #[test]
    fn a_challenged_bond_cannot_be_released() {
        assert!(!may_transition(BondStatus::Challenged, BondStatus::Released));
    }

    #[test]
    fn a_slashed_bond_is_terminal() {
        for to in [
            BondStatus::Attested,
            BondStatus::Challenged,
            BondStatus::Released,
            BondStatus::Slashed,
        ] {
            assert!(!may_transition(BondStatus::Slashed, to));
        }
    }

    #[test]
    fn a_released_bond_is_terminal() {
        for to in [
            BondStatus::Attested,
            BondStatus::Challenged,
            BondStatus::Slashed,
            BondStatus::Released,
        ] {
            assert!(!may_transition(BondStatus::Released, to));
        }
    }

    #[test]
    fn no_status_transitions_to_itself() {
        for status in [
            BondStatus::Attested,
            BondStatus::Challenged,
            BondStatus::Slashed,
            BondStatus::Released,
        ] {
            assert!(!may_transition(status, status));
        }
    }

    // -- release ---------------------------------------------------------

    #[test]
    fn a_bond_is_not_releasable_inside_the_window() {
        assert!(!releasable(BondStatus::Attested, 1_000, 1_500, 3_600));
    }

    #[test]
    fn a_bond_is_releasable_once_the_window_passes() {
        assert!(releasable(BondStatus::Attested, 1_000, 4_600, 3_600));
    }

    #[test]
    fn the_boundary_is_inclusive() {
        assert!(releasable(BondStatus::Attested, 1_000, 4_600, 3_600));
        assert!(!releasable(BondStatus::Attested, 1_000, 4_599, 3_600));
    }

    #[test]
    fn a_challenged_bond_never_becomes_releasable_by_waiting() {
        // The moment a bond is questioned is the moment it must still be there.
        assert!(!releasable(BondStatus::Challenged, 1_000, 1_000_000, 3_600));
    }

    #[test]
    fn a_slashed_or_released_bond_is_not_releasable() {
        assert!(!releasable(BondStatus::Slashed, 0, 1_000_000, 0));
        assert!(!releasable(BondStatus::Released, 0, 1_000_000, 0));
    }

    #[test]
    fn a_clock_that_goes_backwards_does_not_release_early() {
        // saturating_sub, so a now earlier than attested_at reads as zero
        // elapsed rather than wrapping to a huge positive.
        assert!(!releasable(BondStatus::Attested, 5_000, 1_000, 3_600));
    }

    #[test]
    fn a_zero_window_releases_immediately() {
        assert!(releasable(BondStatus::Attested, 1_000, 1_000, 0));
    }

    // -- task ids --------------------------------------------------------

    #[test]
    fn a_normal_task_id_is_accepted() {
        assert!(task_id_ok("qualify-0007", MAX_TASK_ID_LEN));
    }

    #[test]
    fn an_empty_task_id_is_refused() {
        assert!(!task_id_ok("", MAX_TASK_ID_LEN));
    }

    #[test]
    fn a_task_id_longer_than_a_seed_is_refused() {
        // 33 bytes: one past what a PDA seed can carry. Caught here with a
        // named error rather than as MaxSeedLengthExceeded from the runtime.
        assert!(!task_id_ok(&"x".repeat(33), MAX_TASK_ID_LEN));
        assert!(task_id_ok(&"x".repeat(32), MAX_TASK_ID_LEN));
    }

    #[test]
    fn a_multibyte_task_id_is_measured_in_bytes_not_chars() {
        // 16 characters, 32 bytes: right at the limit. Measuring in chars
        // would let a 32-character id through and fail in the runtime.
        let id = "é".repeat(16);
        assert_eq!(id.len(), 32);
        assert!(task_id_ok(&id, MAX_TASK_ID_LEN));
        assert!(!task_id_ok(&"é".repeat(17), MAX_TASK_ID_LEN));
    }
}
