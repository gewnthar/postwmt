# /var/www/postwmt/postwmt_app.py
from app import create_app

# Create the Flask app instance using the factory function
app = create_app()

# The following block is only for running with 'python postwmt_app.py'
# In production, Gunicorn will directly use the 'app' object above via WSGI.
if __name__ == '__main__':
    # Note: Debug should be controlled by FLASK_DEBUG in .env for flask run
    # The host='0.0.0.0' makes it accessible on your network if needed for testing
    app.run(host='0.0.0.0', port=5000)
