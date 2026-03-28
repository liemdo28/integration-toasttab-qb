from pathlib import Path

from sync_ledger import (
    STATUS_BLOCKED_DUPLICATE,
    STATUS_FAILED,
    STATUS_PREVIEW_SUCCESS,
    STATUS_SUCCESS,
    SyncLedger,
    build_report_identity,
)


def _write_report(path: Path, content: bytes):
    path.write_bytes(content)


def test_begin_run_and_mark_success(tmp_path):
    db_path = tmp_path / "sync-ledger.db"
    report_path = tmp_path / "report.xlsx"
    _write_report(report_path, b"report-a")

    identity = build_report_identity(report_path)
    ledger = SyncLedger(db_path)
    result = ledger.begin_run(
        store="Store A",
        date="2026-03-28",
        report_path=report_path,
        report_hash=identity.report_hash,
        report_size=identity.report_size,
        report_mtime=identity.report_mtime,
        ref_number="20260328",
        preview=False,
        strict_mode=True,
        qb_company_file="D:/QB/StoreA.qbw",
    )

    assert result.allowed is True
    ledger.mark_success(result.sync_id, txn_id="TXN123")
    last_run = ledger.get_last_run("Store A", "2026-03-28")
    assert last_run["status"] == STATUS_SUCCESS


def test_same_hash_after_success_blocks_duplicate(tmp_path):
    db_path = tmp_path / "sync-ledger.db"
    report_path = tmp_path / "report.xlsx"
    _write_report(report_path, b"report-a")
    identity = build_report_identity(report_path)
    ledger = SyncLedger(db_path)

    first = ledger.begin_run(
        store="Store A",
        date="2026-03-28",
        report_path=report_path,
        report_hash=identity.report_hash,
        report_size=identity.report_size,
        report_mtime=identity.report_mtime,
        ref_number="20260328",
        preview=False,
        strict_mode=True,
        qb_company_file="D:/QB/StoreA.qbw",
    )
    ledger.mark_success(first.sync_id, txn_id="TXN123")

    second = ledger.begin_run(
        store="Store A",
        date="2026-03-28",
        report_path=report_path,
        report_hash=identity.report_hash,
        report_size=identity.report_size,
        report_mtime=identity.report_mtime,
        ref_number="20260328",
        preview=False,
        strict_mode=True,
        qb_company_file="D:/QB/StoreA.qbw",
    )

    assert second.allowed is False
    assert second.status == STATUS_BLOCKED_DUPLICATE


def test_same_date_different_hash_is_allowed_with_warning_message(tmp_path):
    db_path = tmp_path / "sync-ledger.db"
    report_a = tmp_path / "report-a.xlsx"
    report_b = tmp_path / "report-b.xlsx"
    _write_report(report_a, b"report-a")
    _write_report(report_b, b"report-b")
    identity_a = build_report_identity(report_a)
    identity_b = build_report_identity(report_b)
    ledger = SyncLedger(db_path)

    first = ledger.begin_run(
        store="Store A",
        date="2026-03-28",
        report_path=report_a,
        report_hash=identity_a.report_hash,
        report_size=identity_a.report_size,
        report_mtime=identity_a.report_mtime,
        ref_number="20260328",
        preview=False,
        strict_mode=True,
        qb_company_file="D:/QB/StoreA.qbw",
    )
    ledger.mark_success(first.sync_id, txn_id="TXN123")

    second = ledger.begin_run(
        store="Store A",
        date="2026-03-28",
        report_path=report_b,
        report_hash=identity_b.report_hash,
        report_size=identity_b.report_size,
        report_mtime=identity_b.report_mtime,
        ref_number="20260328",
        preview=False,
        strict_mode=True,
        qb_company_file="D:/QB/StoreA.qbw",
    )

    assert second.allowed is True
    assert "different report version" in second.message.lower()


def test_preview_success_does_not_block_live_sync(tmp_path):
    db_path = tmp_path / "sync-ledger.db"
    report_path = tmp_path / "report.xlsx"
    _write_report(report_path, b"report-a")
    identity = build_report_identity(report_path)
    ledger = SyncLedger(db_path)

    preview_run = ledger.begin_run(
        store="Store A",
        date="2026-03-28",
        report_path=report_path,
        report_hash=identity.report_hash,
        report_size=identity.report_size,
        report_mtime=identity.report_mtime,
        ref_number="20260328",
        preview=True,
        strict_mode=True,
        qb_company_file="",
    )
    ledger.mark_success(preview_run.sync_id, preview=True)
    assert ledger.get_last_run("Store A", "2026-03-28")["status"] == STATUS_PREVIEW_SUCCESS

    live_run = ledger.begin_run(
        store="Store A",
        date="2026-03-28",
        report_path=report_path,
        report_hash=identity.report_hash,
        report_size=identity.report_size,
        report_mtime=identity.report_mtime,
        ref_number="20260328",
        preview=False,
        strict_mode=True,
        qb_company_file="D:/QB/StoreA.qbw",
    )
    assert live_run.allowed is True


def test_stale_running_run_is_marked_failed_and_new_run_is_allowed(tmp_path):
    db_path = tmp_path / "sync-ledger.db"
    report_path = tmp_path / "report.xlsx"
    _write_report(report_path, b"report-a")
    identity = build_report_identity(report_path)
    ledger = SyncLedger(db_path)

    first = ledger.begin_run(
        store="Store A",
        date="2026-03-28",
        report_path=report_path,
        report_hash=identity.report_hash,
        report_size=identity.report_size,
        report_mtime=identity.report_mtime,
        ref_number="20260328",
        preview=False,
        strict_mode=True,
        qb_company_file="D:/QB/StoreA.qbw",
    )
    stale_count = ledger.mark_stale_runs_failed(stale_after_minutes=0)

    assert stale_count == 1
    assert ledger.get_last_run("Store A", "2026-03-28")["status"] == STATUS_FAILED

    second = ledger.begin_run(
        store="Store A",
        date="2026-03-28",
        report_path=report_path,
        report_hash=identity.report_hash,
        report_size=identity.report_size,
        report_mtime=identity.report_mtime,
        ref_number="20260328",
        preview=False,
        strict_mode=True,
        qb_company_file="D:/QB/StoreA.qbw",
    )
    assert second.allowed is True
