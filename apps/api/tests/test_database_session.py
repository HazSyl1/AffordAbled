from app.infrastructure.database.session import normalize_asyncpg_database_url


def test_asyncpg_database_url_converts_sslmode_to_ssl() -> None:
    assert normalize_asyncpg_database_url(
        'postgresql+asyncpg://user:p%40ss@db.example/test?sslmode=require'
    ) == 'postgresql+asyncpg://user:p%40ss@db.example/test?ssl=require'


def test_asyncpg_database_url_keeps_existing_ssl_and_removes_sslmode() -> None:
    assert normalize_asyncpg_database_url(
        'postgresql+asyncpg://user:pass@db.example/test?ssl=require&sslmode=require&application_name=app'
    ) == 'postgresql+asyncpg://user:pass@db.example/test?ssl=require&application_name=app'


def test_database_url_without_asyncpg_is_unchanged() -> None:
    url = 'postgresql://user:pass@db.example/test?sslmode=require'
    assert normalize_asyncpg_database_url(url) == url
