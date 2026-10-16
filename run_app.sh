#!/usr/bin/env bash
# ============================================================
# RUN APP — LORIS (v4_speciale) Native App & Services Launcher
# ============================================================
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

export STREAMLIT_CONFIG_DIR="$DIR/.streamlit"
export PYTHONPATH="$DIR/src:$PYTHONPATH"

# Rilevamento automatico ambiente Python (Marco / Amici / Nuova macchina)
if [ -d "$DIR/.venv" ] && [ -f "$DIR/.venv/bin/python" ]; then
    PYTHON_EXEC="$DIR/.venv/bin/python"
    STREAMLIT_EXEC="$DIR/.venv/bin/streamlit"
elif [ -f "/opt/homebrew/Caskroom/miniforge/base/envs/previsione_spese/bin/python" ]; then
    PYTHON_EXEC="/opt/homebrew/Caskroom/miniforge/base/envs/previsione_spese/bin/python"
    STREAMLIT_EXEC="/opt/homebrew/Caskroom/miniforge/base/envs/previsione_spese/bin/streamlit"
else
    # Verifica se python3 ha già le dipendenze
    if ! python3 -c "import streamlit, pandas, plotly" >/dev/null 2>&1; then
        echo "🔧 Primo avvio rilevato: installazione dipendenze in corso..."
        if ! command -v python3 >/dev/null 2>&1; then
            echo "❌ Python 3 non trovato. Installa Python da https://www.python.org/"
            exit 1
        fi
        python3 -m venv "$DIR/.venv"
        "$DIR/.venv/bin/pip" install --upgrade pip
        "$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt"
        PYTHON_EXEC="$DIR/.venv/bin/python"
        STREAMLIT_EXEC="$DIR/.venv/bin/streamlit"
        echo "✅ Installazione completata!"
    else
        PYTHON_EXEC="python3"
        STREAMLIT_EXEC="streamlit"
    fi
fi

if [ "$1" == "--package" ] || [ "$1" == "package" ]; then
    echo "📦 Creazione pacchetto pulito di condivisione per amici..."
    exec "$PYTHON_EXEC" src/package_for_sharing.py
elif [ "$1" == "--test" ] || [ "$1" == "test" ]; then
    echo "🧪 Esecuzione test suite..."
    exec "$PYTHON_EXEC" -m unittest discover tests
elif [ "$1" == "--build" ]; then
    echo "🔨 Ricostruzione bundle nativo LORIS.app..."
    exec "$PYTHON_EXEC" src/build_macos_app.py
elif [ "$1" == "--api" ]; then
    echo "🚀 Avvio FastAPI Server (v4_speciale)..."
    echo "👉 Documentazione OpenAPI disponibile su: http://localhost:8000/docs"
    cd "$DIR/src"
    exec "$PYTHON_EXEC" -m uvicorn app:app --host 127.0.0.1 --port 8000
elif [ "$1" == "--cli" ]; then
    shift
    exec "$PYTHON_EXEC" src/cli.py "$@"
elif [ "$1" == "status" ] || [ "$1" == "simulate" ] || [ "$1" == "models" ] || [ "$1" == "ask" ] || [ "$1" == "agent" ]; then
    exec "$PYTHON_EXEC" src/cli.py "$@"
elif [ "$1" == "--browser" ]; then
    PORT=8502
    while lsof -i :$PORT >/dev/null 2>&1; do
        PORT=$((PORT + 1))
    done
    echo "🚀 Avvio Dashboard LORIS nel browser web su porta $PORT..."
    exec "$STREAMLIT_EXEC" run src/app_streamlit.py --server.port $PORT
else
    # Default: avvia la vera applicazione desktop nativa LORIS.app
    if [ ! -d "LORIS.app" ]; then
        echo "📦 LORIS.app non trovato, compilazione automatica in corso..."
        "$PYTHON_EXEC" src/build_macos_app.py
    fi
    echo "🐾 Avvio applicazione desktop nativa LORIS.app..."
    open LORIS.app
fi
