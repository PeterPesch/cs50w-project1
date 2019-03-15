"""
Import books.csv into the books table.

This module replaces the contents of the books table
with the contents of the file books.csv.

The tables reviews and reviewlines will also be truncated.
"""

import csv
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.exc import IntegrityError, ProgrammingError, DataError


def main():
    """Import books.csv."""
    # Read csv file
    print()
    print("Reading csv ...")
    try:
        with open('books.csv') as f:
            reader = csv.reader(f)
            # Skip header row
            next(reader)
            # isbn, title, author, year
            books = [
                {
                    "isbn": line[0],
                    "title": line[1],
                    "author": line[2],
                    "year": str(int(line[3]))}
                for line in reader
            ]
    except FileNotFoundError:
        print('Sorry, could not find books.csv!')
        return -1
    except (ValueError, IndexError) as e:
        print(f"Error while reading csv file: {e}")
        return -1
    print(f"{len(books)} books read from csv file.")
    # Set up database connection
    engine = create_engine(os.getenv('DATABASE_URL'))
    db = scoped_session(sessionmaker(bind=engine))
    # Truncate books table
    print()
    print("Truncating books table and related tables ...")
    try:
        result = db.execute('TRUNCATE TABLE reviews')
        result = db.execute('TRUNCATE TABLE books')
        db.commit()
    except ProgrammingError as e:
        print(f'Error truncating tables: {e.orig}')
        return -1
    print("Books tables truncated.")
    # Insert books into book table
    print()
    print("Inserting books into books table.")
    try:
        for booknr in range(len(books)):
            print(".", end="", flush=True)
            book = books[booknr]
            try:
                result = db.execute("""
                INSERT INTO books (isbn, title, author, year_of_publication)
                VALUES (:isbn, :title, :author, :year)
                """, book)
            except (ValueError, DataError, IntegrityError) as e:
                db.rollback()
                print()
                print(f'One or more rows skipped because of {book}')
            if booknr % 50 == 49:
                db.commit()
                print(f" {booknr + 1} books handled.")
    except KeyboardInterrupt as e:
        db.rollback()
        print()
        print(f'Program stopped by user.')
        return
    db.commit()
    print()
    print("Books from the csv have been inserted!.")
    print()
    return

if __name__ == '__main__':
    main()
