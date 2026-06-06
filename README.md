# Margin

Backend (FastAPI) + web de pruebas (Vue) de la app de salud financiera Margin.
Diseño y planes en `docs/superpowers/`.

## Backend — arranque

```bash
cd backend
/opt/homebrew/bin/python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
createdb margin && createdb margin_test   # solo la primera vez
alembic upgrade head
uvicorn app.main:app --reload             # http://127.0.0.1:8000/docs
pytest -v
```
