def configure(**settings):
    return dict(settings)


def default_config():
    return configure(debug=True, verbose=False)
