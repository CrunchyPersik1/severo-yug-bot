import ssl

from app.db import prepare_dsn


def test_strips_pgbouncer_and_sslmode():
    dsn, ssl_arg, cache = prepare_dsn(
        "postgresql://u:p@aws-0-eu.pooler.supabase.com:6543/postgres?sslmode=require&pgbouncer=true"
    )
    assert "pgbouncer" not in dsn
    assert "sslmode" not in dsn
    assert cache == 0, "пулер не поддерживает prepared statements"
    assert ssl_arg is not False


def test_local_connection_without_ssl():
    dsn, ssl_arg, cache = prepare_dsn("postgresql://postgres:postgres@localhost:5432/severo")
    assert ssl_arg is False
    assert cache == 100
    assert dsn.endswith("/severo")


def test_verify_full_uses_real_context():
    _, ssl_arg, _ = prepare_dsn("postgresql://u:p@db.example.com:5432/postgres?sslmode=verify-full")
    assert isinstance(ssl_arg, ssl.SSLContext)
    assert ssl_arg.check_hostname is True


def test_keeps_other_params():
    dsn, _, _ = prepare_dsn("postgresql://u:p@h:5432/postgres?application_name=bot&foo=bar")
    assert "foo=bar" in dsn
    assert "application_name" not in dsn
