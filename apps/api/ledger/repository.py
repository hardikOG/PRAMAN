"""Persistence for the proof ledger: looking up the real previous hash to
chain against, and storing/retrieving signed bundles.

Never updated after insert — every write here is a new row; corrections are
new ledger entries referencing the old hash, never edits (see the
immutability rule on `models.schemas.ProofBundle`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.ledger.chain import GENESIS_HASH
from apps.api.models.schemas import ProofBundle, ProofBundlePayload
from apps.api.models.tables import ProofBundleRow


async def get_latest_payload_hash(session: AsyncSession) -> str:
    """Return the most recently signed bundle's `payload_hash`, or
    `GENESIS_HASH` if the ledger is empty — what the next bundle chains
    against.

    Complexity: O(log n) via the `signed_at` index.
    """
    result = await session.execute(
        select(ProofBundleRow.payload_hash).order_by(ProofBundleRow.signed_at.desc()).limit(1)
    )
    row = result.scalar_one_or_none()
    return row if row is not None else GENESIS_HASH


async def save_proof_bundle(session: AsyncSession, bundle: ProofBundle) -> None:
    """Persist a signed bundle. Complexity: O(n) in payload size (one JSON
    serialization)."""
    session.add(
        ProofBundleRow(
            id=bundle.id,
            decision_id=bundle.decision_id,
            prev_hash=bundle.prev_hash,
            payload_hash=bundle.payload_hash,
            signature=bundle.signature,
            signed_at=bundle.signed_at,
            payload=bundle.payload.model_dump(mode="json"),
        )
    )
    await session.flush()


async def get_proof_bundle(session: AsyncSession, bundle_id: str) -> ProofBundle | None:
    """Fetch a bundle by id, or `None` if it doesn't exist."""
    row = await session.get(ProofBundleRow, bundle_id)
    if row is None:
        return None
    return ProofBundle(
        id=row.id,
        decision_id=row.decision_id,
        prev_hash=row.prev_hash,
        payload_hash=row.payload_hash,
        signature=row.signature,
        signed_at=row.signed_at,
        payload=ProofBundlePayload.model_validate(row.payload),
    )


async def get_proof_bundle_by_decision(
    session: AsyncSession, decision_id: str
) -> ProofBundle | None:
    """Fetch the bundle for a given decision id, or `None` if the decision
    never reached ALLOW (only ALLOWed decisions get a bundle)."""
    result = await session.execute(
        select(ProofBundleRow).where(ProofBundleRow.decision_id == decision_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return ProofBundle(
        id=row.id,
        decision_id=row.decision_id,
        prev_hash=row.prev_hash,
        payload_hash=row.payload_hash,
        signature=row.signature,
        signed_at=row.signed_at,
        payload=ProofBundlePayload.model_validate(row.payload),
    )
