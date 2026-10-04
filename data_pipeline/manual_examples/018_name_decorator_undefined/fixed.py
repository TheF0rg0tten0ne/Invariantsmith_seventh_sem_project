def app_route(path):
    def wrapper(func):
        func.route = path
        return func
    return wrapper


@app_route("/health")
def health_check():
    return {"status": "ok"}
