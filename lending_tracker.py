import streamlit as st
import sqlite3
import pandas as pd
from datetime import date

# ==========================================
# DATABASE INITIALIZATION
# ==========================================
DB_FILE = "lending_firm_v2.db"  # Renamed to handle the new schema safely

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Create Loans table with remaining_principal
    c.execute('''CREATE TABLE IF NOT EXISTS loans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_name TEXT,
                    original_principal REAL,
                    remaining_principal REAL,
                    monthly_roi REAL,
                    start_date TEXT,
                    status TEXT
                )''')
    # Create Payments table
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    loan_id INTEGER,
                    payment_date TEXT,
                    amount REAL,
                    payment_type TEXT
                )''')
    conn.commit()
    conn.close()

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def execute_query(query, params=()):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    conn.close()

def fetch_data(query, params=()):
    conn = sqlite3.connect(DB_FILE)
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

# ==========================================
# STREAMLIT UI APP
# ==========================================
st.set_page_config(page_title="Lending Firm Tracker", layout="wide")
init_db()

st.title("💼 Lending Firm Tracker (Dynamic EMI)")

# Navigation Tabs
tab1, tab2, tab3 = st.tabs(["📊 Active Loans Dashboard", "➕ Issue New Loan", "💰 Record Payment"])

# ------------------------------------------
# TAB 1: DASHBOARD
# ------------------------------------------
with tab1:
    st.subheader("Current Active Loans")
    active_loans = fetch_data("SELECT * FROM loans WHERE status = 'Active'")
    
    if not active_loans.empty:
        # Calculate expected monthly interest based on REMAINING principal
        active_loans['Current EMI'] = active_loans['remaining_principal'] * (active_loans['monthly_roi'] / 100)
        
        # Metrics
        total_remaining = active_loans['remaining_principal'].sum()
        total_monthly_interest = active_loans['Current EMI'].sum()
        
        col1, col2 = st.columns(2)
        col1.metric("Total Outstanding Principal Lent", f"₹ {total_remaining:,.2f}")
        col2.metric("Expected Monthly Interest Yield", f"₹ {total_monthly_interest:,.2f}")
        
        # Formatted Display
        display_df = active_loans[['id', 'customer_name', 'original_principal', 'remaining_principal', 'monthly_roi', 'Current EMI', 'start_date']]
        display_df.columns = ['Loan ID', 'Customer Name', 'Original (₹)', 'Remaining Principal (₹)', 'ROI (%)', 'Next EMI (₹)', 'Start Date']
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No active loans found. Issue a new loan to get started.")

# ------------------------------------------
# TAB 2: ISSUE NEW LOAN
# ------------------------------------------
with tab2:
    st.subheader("Add New Customer Loan")
    with st.form("new_loan_form", clear_on_submit=True):
        name = st.text_input("Customer Name")
        principal = st.number_input("Principal Amount (₹)", min_value=0.0, step=1000.0)
        roi = st.number_input("Monthly ROI (%)", min_value=0.0, step=0.1, help="e.g., 5 for 5%")
        start_dt = st.date_input("Loan Start Date", date.today())
        
        submitted = st.form_submit_button("Issue Loan")
        if submitted and name and principal > 0:
            execute_query(
                """INSERT INTO loans 
                   (customer_name, original_principal, remaining_principal, monthly_roi, start_date, status) 
                   VALUES (?, ?, ?, ?, ?, 'Active')""",
                (name, principal, principal, roi, start_dt)
            )
            st.success(f"Loan issued to {name}. Next EMI will be ₹{(principal * (roi/100)):,.2f}.")
            st.rerun()

# ------------------------------------------
# TAB 3: RECORD PAYMENT
# ------------------------------------------
with tab3:
    st.subheader("Log Collections & Principal Returns")
    active_loans = fetch_data("SELECT * FROM loans WHERE status = 'Active'")
    
    if not active_loans.empty:
        # Create dropdown options showing current remaining principal and current EMI
        loan_options = active_loans.apply(
            lambda x: f"ID: {x['id']} | {x['customer_name']} | Remaining: ₹{x['remaining_principal']} | EMI: ₹{x['remaining_principal']*(x['monthly_roi']/100)}", 
            axis=1
        ).tolist()
        
        selected_loan_str = st.selectbox("Select Active Loan", loan_options)
        selected_loan_id = int(selected_loan_str.split(" | ")[0].replace("ID: ", ""))
        current_remaining = float(selected_loan_str.split("Remaining: ₹")[1].split(" |")[0])
        
        with st.form("payment_form", clear_on_submit=True):
            payment_type = st.radio("Payment Type", ["Interest Payment", "Partial / Full Principal Return"])
            amount = st.number_input("Amount Received (₹)", min_value=0.0, step=500.0)
            pay_date = st.date_input("Payment Date", date.today())
            
            submitted = st.form_submit_button("Record Transaction")
            
            if submitted and amount > 0:
                if payment_type == "Interest Payment":
                    execute_query(
                        "INSERT INTO payments (loan_id, payment_date, amount, payment_type) VALUES (?, ?, ?, 'Interest')",
                        (selected_loan_id, pay_date, amount)
                    )
                    st.success(f"Recorded interest payment of ₹{amount:,.2f}.")
                else:
                    # Logic for Principal Return (Partial or Full)
                    execute_query(
                        "INSERT INTO payments (loan_id, payment_date, amount, payment_type) VALUES (?, ?, ?, 'Principal')",
                        (selected_loan_id, pay_date, amount)
                    )
                    
                    new_principal = current_remaining - amount
                    
                    if new_principal <= 0:
                        # Loan is fully paid off
                        execute_query("UPDATE loans SET remaining_principal = 0, status = 'Closed' WHERE id = ?", (selected_loan_id,))
                        st.success(f"Recorded ₹{amount:,.2f}. Full principal returned. Loan is now Closed.")
                    else:
                        # Partial return: update remaining principal
                        execute_query("UPDATE loans SET remaining_principal = ? WHERE id = ?", (new_principal, selected_loan_id))
                        st.success(f"Recorded partial principal return of ₹{amount:,.2f}. Remaining principal is now ₹{new_principal:,.2f}. Next EMI will drop accordingly.")
                        
                st.rerun()
                
        # Show payment history
        st.divider()
        st.subheader("Recent Transaction History")
        history = fetch_data("""
            SELECT p.payment_date, l.customer_name, p.amount, p.payment_type 
            FROM payments p 
            JOIN loans l ON p.loan_id = l.id 
            ORDER BY p.id DESC LIMIT 10
        """)
        if not history.empty:
            history.columns = ['Date', 'Customer', 'Amount (₹)', 'Type']
            st.dataframe(history, use_container_width=True, hide_index=True)
    else:
        st.info("No active loans available to receive payments.")