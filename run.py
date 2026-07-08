# run.py - Entry point for Unified Flask App

from youcert import create_app

app = create_app()

if __name__ == '__main__':
    # Run both User and Creator services together on the same port
    app.run(debug=True, port=5000)
