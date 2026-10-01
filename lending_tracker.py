import streamlit as st
import pandas as pd
from datetime import date
import psycopg2

# ==========================================
# DATABASE INITIALIZATION
# ==========================================
# Fetches the database URL from Streamlit's secure secrets
DB_URL = st.secrets["DATABASE_URL"]

def get_connection():
    return psycopg2.connect(DB_URL)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS loans (
                    id SERIAL PRIMARY KEY,
                    customer_name TEXT,
                    original_principal NUMERIC,
                    remaining_principal NUMERIC,
                    monthly_roi NUMERIC,
                    start_date DATE,
                    status TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS payments (
                    id SERIAL PRIMARY KEY,
                    loan_id INTEGER,
                    payment_date DATE,
                    amount NUMERIC,
                    payment_type TEXT
                )''')
    conn.commit()
    conn.close()

def execute_query(query, params=()):
    conn = get_connection()
    c = conn.cursor()
    c.execute(query, params)
    conn.commit()
    conn.close()

def fetch_data(query, params=()):
    conn = get_connection()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    return df

# ==========================================
# STREAMLIT UI APP & AUTHENTICATION
# ==========================================
st.set_page_config(page_title="SP Enterprise - Lending System", page_icon="🏢", layout="wide")

# 1. Initialize authentication state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

# 2. Function to verify PIN
def check_pin():
    if st.session_state.pin_input == "223568":
        st.session_state.authenticated = True
    else:
        st.error("Incorrect PIN. Access Denied.")

# 3. Show SP Enterprise PIN screen if not authenticated
if not st.session_state.authenticated:
    st.title("🏢 SP Enterprise")
    st.subheader("Secure Lending Management System")
    st.text_input("Enter your 6-digit PIN to access the dashboard", type="password", key="pin_input", on_change=check_pin)
    st.stop()  # Hides the rest of the app until authenticated

# ==========================================
# MAIN DASHBOARD (Only visible if PIN is correct)
# ==========================================
init_db()

st.title("🏢 SP Enterprise | Lending Management Dashboard")

tab1, tab2, tab3 = st.tabs(["📊 Active Loans Dashboard", "➕ Issue New Loan", "💰 Record Payment"])

with tab1:
    st.subheader("Current Active Loans")
    active_loans = fetch_data("SELECT * FROM loans WHERE status = 'Active'")
    
    if not active_loans.empty:
        active_loans['Current EMI'] = active_loans['remaining_principal'] * (active_loans['monthly_roi'] / 100)
        
        total_remaining = active_loans['remaining_principal'].sum()
        total_monthly_interest = active_loans['Current EMI'].sum()
        
        col1, col2 = st.columns(2)
        col1.metric("Total Outstanding Principal Lent", f"₹ {total_remaining:,.2f}")
        col2.metric("Expected Monthly Interest Yield", f"₹ {total_monthly_interest:,.2f}")
        
        display_df = active_loans[['id', 'customer_name', 'original_principal', 'remaining_principal', 'monthly_roi', 'Current EMI', 'start_date']]
        display_df.columns = ['Loan ID', 'Customer Name', 'Original (₹)', 'Remaining (₹)', 'ROI (%)', 'Next EMI (₹)', 'Start Date']
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No active loans found.")

with tab2:
    st.subheader("Add New Customer Loan")
    with st.form("new_loan_form", clear_on_submit=True):
        name = st.text_input("Customer Name")
        principal = st.number_input("Principal Amount (₹)", min_value=0.0, step=1000.0)
        roi = st.number_input("Monthly ROI (%)", min_value=0.0, step=0.1)
        start_dt = st.date_input("Loan Start Date", date.today())
        
        submitted = st.form_submit_button("Issue Loan")
        if submitted and name and principal > 0:
            execute_query(
                """INSERT INTO loans 
                   (customer_name, original_principal, remaining_principal, monthly_roi, start_date, status) 
                   VALUES (%s, %s, %s, %s, %s, 'Active')""",
                (name, principal, principal, roi, start_dt)
            )
            st.success(f"Loan issued to {name}.")
            st.rerun()

with tab3:
    st.subheader("Log Collections & Principal Returns")
    active_loans = fetch_data("SELECT * FROM loans WHERE status = 'Active'")
    
    if not active_loans.empty:
        loan_options = active_loans.apply(
            lambda x: f"ID: {x['id']} | {x['customer_name']} | Remaining: ₹{x['remaining_principal']}", axis=1
        ).tolist()
        
        selected_loan_str = st.selectbox("Select Active Loan", loan_options)
        selected_loan_id = int(selected_loan_str.split(" | ")[0].replace("ID: ", ""))
        current_remaining = float(selected_loan_str.split("Remaining: ₹")[1])
        
        with st.form("payment_form", clear_on_submit=True):
            payment_type = st.radio("Payment Type", ["Interest Payment", "Partial / Full Principal Return"])
            amount = st.number_input("Amount Received (₹)", min_value=0.0, step=500.0)
            pay_date = st.date_input("Payment Date", date.today())
            
            submitted = st.form_submit_button("Record Transaction")
            
            if submitted and amount > 0:
                if payment_type == "Interest Payment":
                    execute_query(
                        "INSERT INTO payments (loan_id, payment_date, amount, payment_type) VALUES (%s, %s, %s, 'Interest')",
                        (selected_loan_id, pay_date, amount)
                    )
                    st.success("Interest payment recorded.")
                else:
                    execute_query(
                        "INSERT INTO payments (loan_id, payment_date, amount, payment_type) VALUES (%s, %s, %s, 'Principal')",
                        (selected_loan_id, pay_date, amount)
                    )
                    new_principal = current_remaining - amount
                    if new_principal <= 0:
                        execute_query("UPDATE loans SET remaining_principal = 0, status = 'Closed' WHERE id = %s", (selected_loan_id,))
                        st.success("Full principal returned. Loan Closed.")
                    else:
                        execute_query("UPDATE loans SET remaining_principal = %s WHERE id = %s", (new_principal, selected_loan_id))
                        st.success("Partial principal returned.")
                st.rerun()
                
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
