from flask import jsonify


def handle_exception(e):
    response = {"error": str(e)}
    return jsonify(response), 500


def handle_value_error(e):
    response = {"error": str(e)}
    return jsonify(response), 400
