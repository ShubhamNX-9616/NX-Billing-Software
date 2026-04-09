from flask import Flask, render_template
from database import init_db
from routes.customers import customers_bp
from routes.companies import companies_bp
from routes.bills import bills_bp
from routes.cloth_types import cloth_types_bp

app = Flask(__name__)

# Register blueprints
app.register_blueprint(customers_bp, url_prefix="/api")
app.register_blueprint(companies_bp, url_prefix="/api")
app.register_blueprint(bills_bp, url_prefix="/api")
app.register_blueprint(cloth_types_bp, url_prefix="/api")


# Page routes
@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/new-bill")
def new_bill():
    return render_template("new_bill.html")


@app.route("/bill-history")
def bill_history():
    return render_template("bill_history.html")


@app.route("/bills/<int:bill_id>")
def bill_detail(bill_id):
    return render_template("bill_detail.html", bill_id=bill_id)


@app.route("/edit-bill/<int:bill_id>")
def edit_bill(bill_id):
    return render_template("edit_bill.html", bill_id=bill_id)


@app.route("/customers")
def customers():
    return render_template("customers.html")


@app.route("/customers/<int:customer_id>")
def customer_detail(customer_id):
    return render_template("customer_detail.html", customer_id=customer_id)


if __name__ == "__main__":
    init_db()
    app.run(host='0.0.0.0', port=8081, debug=False)
