"""Read-only setup check; this is a utility, not the student pipeline solution."""
import importlib.metadata
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / '.env')
url = os.getenv('DATABASE_URL')
if not url:
    sys.exit('DATABASE_URL missing: copy starter/.env.example to starter/.env first.')

packages = (
    'huggingface-hub',
    'numpy',
    'psycopg',
    'pypdf',
    'python-dotenv',
    'safetensors',
    'scikit-learn',
    'scipy',
    'sentence-transformers',
    'tokenizers',
    'torch',
    'transformers',
)
try:
    versions = ', '.join(f'{name} {importlib.metadata.version(name)}' for name in packages)
except importlib.metadata.PackageNotFoundError as error:
    sys.exit(f'Required package missing: {error.name}. Run python -m pip install -r requirements.txt.')
print(f'Python: {sys.version.split()[0]} | {versions}')

try:
    with psycopg.connect(url, connect_timeout=5) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_database(), current_setting('server_version'), extversion "
                "FROM pg_extension WHERE extname = 'vector'"
            )
            row = cursor.fetchone()
            if not row:
                sys.exit('Connected, but pgvector extension is missing. See starter/README.md.')
            print(f'Database: {row[0]} | PostgreSQL: {row[1]} | pgvector: {row[2]}')
except psycopg.Error:
    sys.exit('Database connection failed. Check Docker, port and DATABASE_URL in starter/.env.')
print('Setup OK. Validate the benchmark with `python -m src.run --validate-only`.')
