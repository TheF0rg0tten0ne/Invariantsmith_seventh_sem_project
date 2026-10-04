@app_route("/health")
def health_check():
    return {"status": "ok"}
