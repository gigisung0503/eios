"""Export all user-defined tables from a SQLite database to a single Excel workbook.

This script connects to a SQLite database, enumerates all tables defined by the
application (skipping SQLite's internal tables), then writes each table's data
into a separate worksheet within an Excel file. Only the data is exported –
table schema definitions and internal SQLite metadata tables are omitted.

Usage (from the command line):

    python export_sqlite_to_excel.py /path/to/app.db
    # Optionally specify an output filename
    python export_sqlite_to_excel.py /path/to/app.db --output my_export.xlsx

If --output is omitted, the script derives a filename from the database name
with a ``.xlsx`` extension, writing the Excel file into the current
working directory. The generated workbook will contain one sheet per table.

Requirements:
    - pandas
    - openpyxl

These libraries are installed as part of the project dependencies.
"""

import argparse
import os
import re
import sqlite3
from datetime import datetime
from typing import List

import pandas as pd


def sanitize_sheet_name(name: str) -> str:
    """Return a safe Excel sheet name.

    Excel restricts sheet names to 31 characters and prohibits certain
    characters. This helper truncates long names, removes illegal
    characters and ensures the result is non-empty.
    """
    # Replace illegal characters with underscore
    safe = re.sub(r"[:\\/*\?\[\]]", "_", name)
    # Truncate to 31 characters
    safe = safe[:31]
    return safe or "Sheet"


def get_user_tables(conn: sqlite3.Connection) -> List[str]:
    """Return a list of user-defined tables from the SQLite database.

    SQLite stores internal bookkeeping tables in the ``sqlite_master`` table
    whose names begin with ``sqlite_``. Those should be excluded from
    exports because they do not hold application data.
    """
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    rows = cursor.fetchall()
    return [row[0] for row in rows]


def auto_size_columns(worksheet, dataframe: pd.DataFrame) -> None:
    """Auto-size worksheet columns based on the length of data.

    Adjust the width of each column to fit the longest entry in the column,
    capping widths to a reasonable maximum. This improves readability of
    exported Excel files when viewed in spreadsheet software.
    """
    from openpyxl.utils import get_column_letter

    # Determine width for each column
    for idx, col in enumerate(dataframe.columns, start=1):
        # Convert all values to strings (protect None) and include header name
        values = [str(col)] + ["" if v is None else str(v) for v in dataframe[col]]
        # Find longest value in this column
        max_length = max(len(v) for v in values)
        # Add padding and bound the width
        width = min(max_length + 2, 80)
        col_letter = get_column_letter(idx)
        worksheet.column_dimensions[col_letter].width = width


def export_sqlite_to_excel(db_path: str, output_path: str) -> None:
    """Connect to the SQLite database at ``db_path`` and write tables to Excel.

    Each user-defined table becomes a separate sheet in the workbook.
    The workbook is saved to ``output_path``. If no tables are found, the
    script raises a ValueError.
    """
    if not os.path.isfile(db_path):
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    # Establish a connection. We allow SQLite to handle thread-safety for
    # concurrent reads, but this script operates in a single thread.
    conn = sqlite3.connect(db_path)
    try:
        tables = get_user_tables(conn)
        if not tables:
            raise ValueError(
                "No user-defined tables found in the database. Nothing to export."
            )

        # Create a Pandas ExcelWriter using openpyxl engine
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            for table_name in tables:
                # Read entire table into a DataFrame
                df = pd.read_sql_query(f'SELECT * FROM "{table_name}"', conn)
                sheet_name = sanitize_sheet_name(table_name)
                df.to_excel(writer, sheet_name=sheet_name, index=False)

                # Auto-size columns for readability
                worksheet = writer.sheets[sheet_name]
                auto_size_columns(worksheet, df)

        print(f"Exported {len(tables)} tables to {output_path}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Export all user-defined tables from a SQLite database into an Excel workbook."
        )
    )
    parser.add_argument(
        "db_path",
        help="Path to the SQLite database file (e.g., app.db)",
    )
    parser.add_argument(
        "--output",
        dest="output",
        default=None,
        help=(
            "Optional output Excel filename. Defaults to the database name with .xlsx extension."
        ),
    )

    args = parser.parse_args()
    db_path = os.path.abspath(args.db_path)

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        # Use database filename without extension and add .xlsx
        base_name = os.path.splitext(os.path.basename(db_path))[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"{base_name}_export_{timestamp}.xlsx"

    export_sqlite_to_excel(db_path, output_path)


if __name__ == "__main__":
    main()