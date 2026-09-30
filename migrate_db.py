import sqlite3
import os

OLD_DB = "lending_firm.db"
NEW_DB = "lending_firm_v2.db"

def migrate_database():
    if not os.path.exists(OLD_DB):
        print(f"Error: Could not find the old database '{OLD_DB}'.")
        return

    print(f"Starting migration from {OLD_DB} to {NEW_DB}...")

    # Connect to the NEW database (this will create it if it doesn't exist)
    conn = sqlite3.connect(NEW_DB)
    c = conn.cursor()

    # 1. Create the new schema tables
    c.execute('''CREATE TABLE IF NOT EXISTS loans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_name TEXT,
                    original_principal REAL,
                    remaining_principal REAL,
                    monthly_roi REAL,
                    start_date TEXT,
                    status TEXT
                )''')

    c.execute('''CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    loan_id INTEGER,
                    payment_date TEXT,
                    amount REAL,
                    payment_type TEXT
                )''')

    # 2. Attach the OLD database to this connection
    c.execute(f"ATTACH DATABASE '{OLD_DB}' AS v1_db")

    try:
        # 3. Migrate Loans
        # Maps principal_amount -> original_principal
        # Calculates remaining_principal based on whether the loan was closed in v1
        print("Migrating loans...")
        c.execute("""
            INSERT INTO loans (id, customer_name, original_principal, remaining_principal, monthly_roi, start_date, status)
            SELECT 
                id, 
                customer_name, 
                principal_amount, 
                CASE 
                    WHEN status = 'Closed' THEN 0 
                    ELSE principal_amount 
                END,
                monthly_roi, 
                start_date, 
                status
            FROM v1_db.loans
        """)
        
        # 4. Migrate Payments
        # Exact 1:1 mapping for payments
        print("Migrating payment history...")
        c.execute("""
            INSERT INTO payments (id, loan_id, payment_date, amount, payment_type)
            SELECT id, loan_id, payment_date, amount, payment_type
            FROM v1_db.payments
        """)

        conn.commit()
        print("✅ Migration completed successfully!")

    except sqlite3.IntegrityError:
        print("\n❌ Error: ID collision detected. Please delete any existing 'lending_firm_v2.db' file and run this script again on a fresh database.")
    except Exception as e:
        print(f"\n❌ An error occurred: {e}")
    finally:
        # Clean up
        c.execute("DETACH DATABASE v1_db")
        conn.close()

if __name__ == "__main__":
    migrate_database()