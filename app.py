from flask import Flask, request, render_template_string
from local_db_main import query_engine
from logging_config import get_logger

app = Flask(__name__)
logger = get_logger(__name__)

PAGE = """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Calendar Insights Q&A</title>
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 24px; background: #0b1020; color: #e6eaf2; }
      h1 { margin: 0 0 8px; font-size: 22px; }
      p { margin: 0 0 16px; color: #aab3c5; }
      form { display: flex; gap: 8px; margin-bottom: 16px; }
      input[type=text] { flex: 1; padding: 12px; border-radius: 8px; border: 1px solid #2a3554; background: #121a35; color: #e6eaf2; }
      button { padding: 12px 16px; border: 0; border-radius: 8px; background: #4f6af0; color: white; cursor: pointer; }
      button:hover { background: #3f58d0; }
      .card { border: 1px solid #223058; background: #0f1733; padding: 16px; border-radius: 10px; }
      .label { font-size: 12px; color: #9aa6bf; margin-bottom: 6px; }
      pre { white-space: pre-wrap; word-wrap: break-word; }
      .meta { font-size: 12px; color: #9aa6bf; margin-top: 8px; }
    </style>
  </head>
  <body>
    <h1>Calendar Insights Q&A</h1>
    <p>Ask a question about your Oracle data. We'll route to the right tables with the enhanced context.</p>

    <form method="POST">
      <input type="text" name="q" placeholder="e.g., Show meetings hosted by Surya Yadavalli" value="{{ q or '' }}" />
      <button type="submit">Ask</button>
    </form>

    {% if error %}
      <div class="card"><div class="label">Error</div><pre>{{ error }}</pre></div>
    {% endif %}

    {% if answer %}
      <div class="card">
        <div class="label">Answer</div>
        <pre>{{ answer }}</pre>
        {% if sql %}
        <div class="meta">Generated SQL (if available):</div>
        <pre>{{ sql }}</pre>
        {% endif %}
      </div>
    {% endif %}
  </body>
</html>
"""

@app.route("/", methods=["GET", "POST"])
def home():
    q = None
    answer_text = None
    sql_text = None
    error_text = None

    if request.method == "POST":
        q = (request.form.get("q") or "").strip()
        if q:
            try:
                # Append a short guard instruction to avoid semicolons in generated SQL
                q_guarded = q + "\n\nNote: Do NOT end SQL statements with a semicolon (;) — driver will error."
                logger.info(f"Processing query: {q}")
                resp = query_engine.query(q_guarded)
                answer_text = str(resp)
                logger.info(f"Query response received, length: {len(answer_text)} characters")
                try:
                    meta = getattr(resp, "metadata", None) or {}
                    sql_text = meta.get("sql_query") or meta.get("sql") or None
                    if sql_text:
                        logger.debug(f"Generated SQL: {sql_text}")
                except Exception as e:
                    logger.warning(f"Failed to extract SQL metadata: {e}")
                    sql_text = None
            except Exception as e:
                logger.error(f"Error processing query: {e}", exc_info=True)
                error_text = str(e)
        else:
            error_text = "Please enter a question."

    return render_template_string(PAGE, q=q, answer=answer_text, sql=sql_text, error=error_text)

if __name__ == "__main__":
    # Run on localhost:5001 to avoid conflicts
    app.run(host="127.0.0.1", port=5001, debug=False)
