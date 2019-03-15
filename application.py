from hashlib import sha224
import os

from flask import Flask, session, render_template, request, redirect, url_for
from flask_session import Session
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

app = Flask(__name__)

# Check for environment variable
if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL is not set")

# Configure session to use filesystem
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Set up database
engine = create_engine(os.getenv("DATABASE_URL"))
db = scoped_session(sessionmaker(bind=engine))

# Set up GoodReads access
goodreadsapi = os.getenv("GOODREADS_API")

# Define uniform way to get current username
def get_username():
    """Get the current username."""
    userid = session.get("userid")
    if userid is None:
        return None
    # Fetch username
    try:
        result = db.execute("""
        SELECT username FROM readers
        WHERE reader_id = :reader_id
        """, {"reader_id": userid})
    except Exception as e:
        return None
    row = result.fetchone()
    return row[0]


# Define uniform way to check password
def check_password(username, password):
    """Check the password"""
    # Fetch reader
    hash = get_hash(password)
    try:
        result = db.execute("""
        SELECT reader_id FROM readers
        WHERE username = :username and passwordhash = :passwordhash
        """, {"username": username, "passwordhash": hash})
    except Exception as e:
        return None
    row = result.fetchone()
    if not row:
        return None
    return row[0]


def errors_in_username(name):
    """Check whether username is legal"""
    if len(name) < 2:
        return "Username should contain at least 2 characters!"
    try:
        result = db.execute("""
        SELECT username FROM readers
        WHERE username = :username
        """, {'username': name})
    except Exception as e:
        return f"Could not check username: {name}"
    row = result.fetchone()
    if row:
        return f"Username allready in use: {row}"
    # No errors found:
    return False


def errors_in_password(pw):
    """Check whether password is legal"""
    if len(pw) < 4:
        return "Password should contain at least 4 characters!"
    # No errors found:
    return False


def add_reader(name, hash):
    """Add user to database."""
    try:
        result = db.execute("""
        INSERT INTO readers (username, passwordhash)
        VALUES (:username, :passwordhash)
        """, {"username": name, "passwordhash": hash})
        db.commit()
    except Exception as e:
        return None, f"Could not add reader: {name}"
    # Fetch user_id
    try:
        result = db.execute("""
        SELECT reader_id FROM readers
        WHERE username = :username
        """, {"username": name})
    except Exception as e:
        return None, f"Could not fetch reader: {name}"
    row = result.fetchone()
    if not row:
        return None, f"Could not fetch user_id: {name}"
    return row[0], False


def get_hash(pw):
    """Get hash value for password"""
    return sha224(pw.encode("utf-8")).hexdigest()


def cleanse_user():
    """"Cleanse user from session."""
    session.pop("userid", None)
    session.pop("searchdata", None)
    session.pop("isbn", None)


def select_books(title, author, isbn):
    """Select books with search criteria."""
    title = f"%{title}%"
    author = f"%{author}%"
    isbn = f"%{isbn}%"
    try:
        result = db.execute("""
        SELECT isbn, title, author, year_of_publication
        FROM books
        WHERE isbn like :isbn
        AND title like :title
        AND author like :author
        """, {'isbn': isbn, 'title': title, 'author': author})
    except Exception as e:
        return f"Could not search books: ({title} - {author} - {isbn})"
    return result.fetchall()


def select_book(isbn):
    """Select book with given isbn number."""
    try:
        result = db.execute("""
        SELECT isbn, title, author, year_of_publication
        FROM books
        WHERE isbn = :isbn
        """, {'isbn': isbn})
    except Exception as e:
        return f"Could not search book: {isbn}"
    return result.fetchone()


def select_review(isbn, userid):
    """Select review from current user for current book."""
    try:
        result = db.execute("""
        SELECT rating, review
        FROM reviews
        WHERE isbn = :isbn
        AND reader_id = :reader_id
        """, {'isbn': isbn, 'reader_id': userid})
        if not result:
            return None
        row = result.fetchone()
        rating = int(row[0])
        review = row[1]
        return (rating, review)
    except Exception as e:
        return None


def select_reviews(isbn, userid):
    """Select reviews from other users for current book."""
    try:
        result = db.execute("""
        SELECT rating, review
        FROM reviews
        WHERE isbn = :isbn
        AND NOT reader_id = :reader_id
        """, {'isbn': isbn, 'reader_id': userid})
        return result.fetchall()
    except Exception as e:
        return None


def submit_review(isbn, userid, rating, review):
    """Submit rating and review."""
    try:
        db.execute("""
        DELETE FROM reviews
        WHERE isbn = :isbn and reader_id = :reader_id
        """, {"isbn": isbn, "reader_id": userid})
        result = db.execute("""
        INSERT INTO reviews (isbn, reader_id, rating, review)
        VALUES (:isbn, :reader_id, :rating, :review)
        """, {
            "isbn": isbn, "reader_id": userid,
            "rating": rating, "review": review
        })
        db.commit()
    except Exception as e:
        return None, f"Could not add review."


def fetch_goodreads_rating(isbn):
    """Fetch GoodReads rating for this book."""
    result = requests.get(
        "https://www.goodreads.com/book/review_counts.json",
        params={"key": goodreadsapi, "isbns": isbn}
    )
    if not result:
        return None
    book = result.json()["books"][0]
    rating =book.get("average_rating", None)
    number = book.get("work_ratings_count", None)
    return (rating, number)


@app.route("/")
def index():
    username = get_username()
    if username:
        return redirect(url_for("search"))
    else:
        return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    username = get_username()
    pagetitle = "Registration"
    if request.method == "POST":
        cleanse_user()
        # Check entries
        entered_password = request.form.get("password")
        error = errors_in_password(entered_password)
        entered_username = request.form.get("name")
        if not error:
            error = errors_in_username(entered_username)
        # Register new reader if no errors
        hash = get_hash(entered_password)
        if not error:
            userid, error = add_reader(entered_username, hash)
        # Done
        if error: 
            return render_template(
                "register.html", pagetitle=pagetitle,
                error=error)
        else:
            session["userid"] = userid
            return redirect(url_for("search"))
    return render_template("register.html", pagetitle=pagetitle, username=username)


@app.route("/login", methods=["GET", "POST"])
def login():
    pagetitle = "Log In"
    error = None
    if request.method == "POST":
        cleanse_user()
        entered_username = request.form.get("name")
        entered_password = request.form.get("password")
        userid = check_password(entered_username, entered_password)
        if userid:
            session["userid"] = userid
            return redirect(url_for("search"))
        else:
            error = "Incorrect Username or Password!"
            cleanse_user()
    username = get_username()
    return render_template(
        "login.html", pagetitle=pagetitle, username=username,
        error=error)

@app.route("/logout")
def logout():
    """Log out of the application."""
    cleanse_user()
    return redirect(url_for("login"))

@app.route("/search", methods=["GET", "POST"])
def search():
    username = get_username()
    pagetitle = "Search Books"
    if request.method == "POST":
        # Check entries
        title = request.form.get("title")
        author = request.form.get("author")
        isbn = request.form.get("isbn")
        if len(title) + len(author) + len(isbn) == 0:
            error = "At least one search field should be filled!"
            session.pop("searchdata", None)
            return render_template(
                "search.html", pagetitle=pagetitle, username=username,
                error=error)
        else:
            session["searchdata"] = {
                "title": title,
                "author": author,
                "isbn": isbn
            }
            return redirect(url_for('results'))
    return render_template("search.html", pagetitle=pagetitle, username=username)

@app.route("/results")
def results():
    username = get_username()
    searchdata = session.get("searchdata", None)
    session.pop("review", None)
    if not searchdata:
        return redirect(url_for("search"))
    # Fetch results from csv
    results = select_books(
        isbn=searchdata.get("isbn", ""),
        title=searchdata.get("title", ""),
        author=searchdata.get("author", "")
    )
    # isbn, title, author, pubyear
    pagetitle = "Search Results"
    return render_template("results.html", pagetitle=pagetitle, results=results, username=username)

@app.route("/book/<string:isbn>", methods=["GET", "POST"])
def book(isbn):
    username = get_username()
    my_rating = None
    my_review = ""
    error = None
    bookerror = None

    # Select review by current user
    userid = session.get("userid", None)
    review_submitted = False
    if userid:
        result = select_review(isbn=isbn, userid=userid)
        if result:
            (my_rating, my_review) = result
            review_submitted = True

    # isbn, title, author, year_of_publication

    # Fetch Book Info from database
    book = select_book(isbn=isbn)
    if book:
        title = book[1]
        author = book[2]
        pubyear = book[3]
    else:
        title = "?"
        author = "?"
        pubyear = "?"
        bookerror = f"Could not find ISBN {isbn}."
    bookinfo = {"title": title, "author": author, "pubyear": pubyear, "isbn": isbn}
    pagetitle = bookinfo["title"]

    # Fetch rating info from GoodReads
    ratinginfo = fetch_goodreads_rating(isbn)
    if ratinginfo:
        avgrating = ratinginfo[0]
        nrofratings = ratinginfo[1]
        goodreads_ratinginfo = {"avg": avgrating, "nr": nrofratings}
    else:
        goodreads_ratinginfo = None

    # Fetch other reviews from database
    reviews = select_reviews(isbn=isbn, userid=userid)
    # reviews.append({
    #     "rating": 5,
    #     "lines": [
    #         "this book rocked my world, and i've been trying for weeks to understand why. here it is:",
    #         "* because the plot is flawless",
    #         "* because the voice is flawless",
    #         "* because it's amazingly tender without being cute",
    #         "* because there's a christopher boone in me, and a christopher boone in everyone i love or at least try to get along with"
    # ]})
    # reviews.append({
    #     "rating": 4,
    #     "lines": [
    #     "I haven’t read a fictional account this heartbreakingly realistic in a long time.",
    #     "Kapitoil was close, but The Curious Incident paints a more complete picture."
    # ]})
    # reviews.append({
    #     "rating": 5,
    #     "lines": [
    #     "This is the story of Christopher Boone, a very likable 15 year old who suffers from Asperger Syndrome, a type of higher functioning Autism.",
    #     "Christopher sets out to solve a mystery; who killed Wellington, his neighbors dog, something he wants very much to do because he is accused of committing the crime.",
    #     "Christopher’s detective work helps him solve some other mysteries along the way, one that is much more important than who killed Wellington."
    # ]})

    # Calculate rating info
    if reviews:
        sum_of_ratings = sum([r["rating"] for r in reviews])
        avgrating = round(sum_of_ratings / len(reviews), 2)
        nrofratings = len(reviews)
        # ratinginfo = [avgrating, nrofratings]
        ratinginfo = {"avg": avgrating, "nr": nrofratings}
    else:
        ratinginfo = []

    if request.method == "POST":
        my_review = request.form.get("review")
        my_rating = request.form.get("rating")
        if not my_rating:
            error = "Please enter a rating!"
        error = submit_review(
            isbn=isbn, userid=userid, rating=my_rating, review=my_review)

    return render_template(
        "book.html",
        pagetitle=pagetitle,
        bookinfo=bookinfo,
        goodreads_ratinginfo=goodreads_ratinginfo,
        ratinginfo=ratinginfo,
        my_rating=my_rating,
        my_review=my_review,
        reviews=reviews, username=username,
        review_submitted=review_submitted,
        bookerror=bookerror,
        error = error)
