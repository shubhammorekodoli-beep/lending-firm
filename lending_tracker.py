import streamlit as st
import pandas as pd
from datetime import date
import psycopg2
import sqlite3
import os
import smtplib
from email.message import EmailMessage
from fpdf import FPDF
import tempfile

# ==========================================
# DATABASE INITIALIZATION
# ==========================================
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

def migrate_local_to_cloud():
    local_db = "lending_firm_v2.db" if os.path.exists("lending_firm_v2.db") else "lending_firm.db"
    if not os.path.exists(local_db):
        st.error(f"❌ Could not find '{local_db}' in the application folder.")
        return
    try:
        sl_conn = sqlite3.connect(local_db)
        sl_cur = sl_conn.cursor()
        pg_conn = get_connection()
        pg_cur = pg_conn.cursor()
        
        sl_cur.execute("PRAGMA table_info(loans)")
        columns = [info[1] for info in sl_cur.fetchall()]
        
        if "remaining_principal" in columns:
            sl_cur.execute("SELECT id, customer_name, original_principal, remaining_principal, monthly_roi, start_date, status FROM loans")
        else:
            sl_cur.execute("SELECT id, customer_name, principal_amount, principal_amount, monthly_roi, start_date, status FROM loans")
            
        loans = sl_cur.fetchall()
        for loan in loans:
            pg_cur.execute(
                """INSERT INTO loans (id, customer_name, original_principal, remaining_principal, monthly_roi, start_date, status) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
                loan
            )
        pg_cur.execute("SELECT setval(pg_get_serial_sequence('loans', 'id'), coalesce(max(id),0) + 1, false) FROM loans;")

        sl_cur.execute("SELECT id, loan_id, payment_date, amount, payment_type FROM payments")
        payments = sl_cur.fetchall()
        for payment in payments:
            pg_cur.execute(
                """INSERT INTO payments (id, loan_id, payment_date, amount, payment_type) 
                   VALUES (%s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
                payment
            )
        pg_cur.execute("SELECT setval(pg_get_serial_sequence('payments', 'id'), coalesce(max(id),0) + 1, false) FROM payments;")
        pg_conn.commit()
        st.success("✅ Successfully migrated all local data to Supabase Cloud!")
    except Exception as e:
        st.error(f"❌ An error occurred: {e}")
    finally:
        if 'sl_conn' in locals(): sl_conn.close()
        if 'pg_conn' in locals(): pg_conn.close()

# ==========================================
# REPORT GENERATION & EMAIL LOGIC
# ==========================================
def calc_next_emi(start_dt):
    next_date = pd.to_datetime(start_dt)
    while next_date.date() <= date.today():
        next_date += pd.DateOffset(months=1)
    return next_date.date()

def generate_pdf(df):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("helvetica", size=16, style="B")
    pdf.cell(0, 10, "SP Enterprise - Pending & Upcoming EMIs", ln=True, align='C')
    pdf.ln(5)
    
    pdf.set_font("helvetica", size=10)
    pdf.cell(0, 10, f"Generated on: {date.today()}", ln=True, align='R')
    pdf.ln(5)
    
    if df.empty:
        pdf.cell(0, 10, "No pending EMIs found.", ln=True)
    else:
        for index, row in df.iterrows():
            # Formatting each loan as a text block for clean mobile viewing
            pdf.set_font("helvetica", size=11, style="B")
            pdf.cell(0, 8, f"Customer: {row['customer_name']}", ln=True)
            
            pdf.set_font("helvetica", size=10)
            pdf.cell(0, 6, f"   Remaining Principal: Rs {row['remaining_principal']:,.2f}", ln=True)
            pdf.cell(0, 6, f"   Next EMI Date: {row['Next EMI Date']} | Amount Due: Rs {row['Current EMI']:,.2f}", ln=True)
            pdf.ln(4)
            
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(tmp_file.name)
    return tmp_file.name

def email_report(pdf_path):
    try:
        sender_email = st.secrets["EMAIL_SENDER"]
        sender_pwd = st.secrets["EMAIL_PASSWORD"]
        receiver_email = "santosh.padwal1@gmail.com"
        
        msg = EmailMessage()
        msg['Subject'] = f"SP Enterprise: Pending EMIs Report - {date.today()}"
        msg['From'] = sender_email
        msg['To'] = receiver_email
        msg.set_content("Hello,\n\nPlease find the attached PDF report detailing the pending and upcoming EMIs for active loans.\n\nBest,\nSP Enterprise System")
        
        with open(pdf_path, 'rb') as f:
            pdf_data = f.read()
            
        msg.add_attachment(pdf_data, maintype='application', subtype='pdf', filename=f'EMI_Report_{date.today()}.pdf')
        
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_pwd)
            server.send_message(msg)
            
        return True
    except Exception as e:
        st.error(f"Email failed to send. Error: {e}")
        return False

# ==========================================
# STREAMLIT UI APP & AUTHENTICATION
# ==========================================
st.set_page_config(page_title="SP Enterprise - Lending System", page_icon="🏢", layout="wide")

if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
    st.session_state.current_user = None

VALID_USERS = {
    "shubham.more": "shubham.18",
    "santosh.padwal": "santosh.11"
}

def authenticate():
    user = st.session_state.username_input
    pwd = st.session_state.password_input
    if user in VALID_USERS and VALID_USERS[user] == pwd:
        st.session_state.authenticated = True
        st.session_state.current_user = user
    else:
        st.error("Invalid Username or Password. Access Denied.")

if not st.session_state.authenticated:
    st.title("🏢 SP Enterprise")
    st.subheader("Secure Lending Management System")
    
    with st.form("login_form"):
        st.text_input("Username", key="username_input")
        st.text_input("Password", type="password", key="password_input")
        st.form_submit_button("Log In", on_click=authenticate, type="primary")
        
    st.stop() 

# ==========================================
# MAIN DASHBOARD 
# ==========================================
init_db()

col1, col2 = st.columns([0.8, 0.2])
with col1:
    st.title("🏢 SP Enterprise | Lending Management")
with col2:
    st.write(f"👤 Logged in as: **{st.session_state.current_user}**")
    if st.button("Log Out"):
        st.session_state.authenticated = False
        st.rerun()

tab1, tab2, tab3, tab4, tab5 = st.tabs(["📊 Active Loans Dashboard", "➕ Issue New Loan", "💰 Record Payment", "🛠️ Manage & Admin", "📧 Email Reports"])

# --- TAB 1: ACTIVE LOANS ---
with tab1:
    st.subheader("Current Active Loans")
    active_loans = fetch_data("""
        SELECT l.*, 
               COALESCE((SELECT SUM(amount) FROM payments p WHERE p.loan_id = l.id AND p.payment_type = 'Interest'), 0) as total_interest_collected 
        FROM loans l 
        WHERE l.status = 'Active'
    """)
    
    if not active_loans.empty:
        active_loans['Next EMI Date'] = active_loans['start_date'].apply(calc_next_emi)
        active_loans['Current EMI'] = active_loans['remaining_principal'] * (active_loans['monthly_roi'] / 100)
        
        total_remaining = active_loans['remaining_principal'].sum()
        total_monthly_interest = active_loans['Current EMI'].sum()
        total_historical_interest = active_loans['total_interest_collected'].sum()
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Outstanding Principal", f"₹ {total_remaining:,.2f}")
        col2.metric("Expected Monthly Yield", f"₹ {total_monthly_interest:,.2f}")
        col3.metric("Total Interest Collected", f"₹ {total_historical_interest:,.2f}")
        
        display_df = active_loans[['id', 'customer_name', 'original_principal', 'remaining_principal', 'total_interest_collected', 'monthly_roi', 'Current EMI', 'Next EMI Date']]
        display_df.columns = ['Loan ID', 'Customer Name', 'Original (₹)', 'Remaining (₹)', 'Interest Gained (₹)', 'ROI (%)', 'Next EMI (₹)', 'Next EMI Date']
        st.dataframe(display_df, use_container_width=True, hide_index=True)
    else:
        st.info("No active loans found.")

# --- TAB 2: ISSUE LOAN ---
with tab2:
    st.subheader("Add New Customer Loan")
    with st.form("new_loan_form", clear_on_submit=True):
        name = st.text_input("Customer Name")
        principal = st.number_input("Principal Amount (₹)", min_value=0.0, step=1000.0)
        roi = st.number_input("Monthly ROI (%)", min_value=0.0, step=0.1)
        start_dt = st.date_input("Loan Start Date", date.today())
        
        submitted = st.form_submit_button("Submit New Loan", type="primary")
        if submitted and name and principal > 0:
            execute_query(
                """INSERT INTO loans 
                   (customer_name, original_principal, remaining_principal, monthly_roi, start_date, status) 
                   VALUES (%s, %s, %s, %s, %s, 'Active')""",
                (name, principal, principal, roi, start_dt)
            )
            st.success(f"Loan issued successfully to {name}.")
            st.rerun()

# --- TAB 3: RECORD PAYMENT ---
with tab3:
    st.subheader("Log Collections & Principal Returns")
    active_loans_dropdown = fetch_data("SELECT * FROM loans WHERE status = 'Active'")
    
    if not active_loans_dropdown.empty:
        loan_options = active_loans_dropdown.apply(
            lambda x: f"ID: {x['id']} | {x['customer_name']} | Remaining: ₹{x['remaining_principal']}", axis=1
        ).tolist()
        
        selected_loan_str = st.selectbox("Select Active Loan", loan_options)
        selected_loan_id = int(selected_loan_str.split(" | ")[0].replace("ID: ", ""))
        current_remaining = float(selected_loan_str.split("Remaining: ₹")[1])
        
        with st.form("payment_form", clear_on_submit=True):
            payment_type = st.radio("Payment Type", ["Interest Payment", "Partial / Full Principal Return"])
            amount = st.number_input("Amount Received (₹)", min_value=0.0, step=500.0)
            pay_date = st.date_input("Date of Record", date.today())
            
            submitted = st.form_submit_button("Payment Received", type="primary")
            
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

# --- TAB 4: MANAGE & ADMIN ---
with tab4:
    st.subheader("Edit or Delete Existing Loans")
    active_loans_manage = fetch_data("SELECT * FROM loans WHERE status = 'Active'")
    
    if not active_loans_manage.empty:
        manage_options = active_loans_manage.apply(
            lambda x: f"ID: {x['id']} | {x['customer_name']}", axis=1
        ).tolist()
        
        selected_manage_str = st.selectbox("Select Loan to Modify", manage_options, key="manage_select")
        manage_loan_id = int(selected_manage_str.split(" | ")[0].replace("ID: ", ""))
        
        loan_detail = active_loans_manage[active_loans_manage['id'] == manage_loan_id].iloc[0]
        
        with st.form("edit_loan_form"):
            st.write("**Edit Loan Details**")
            edit_name = st.text_input("Customer Name", value=loan_detail['customer_name'])
            edit_roi = st.number_input("Monthly ROI (%)", min_value=0.0, step=0.1, value=float(loan_detail['monthly_roi']))
            edit_remaining = st.number_input("Remaining Principal (₹)", min_value=0.0, step=500.0, value=float(loan_detail['remaining_principal']))
            
            update_submitted = st.form_submit_button("Update Loan Record")
            
            if update_submitted:
                execute_query("UPDATE loans SET customer_name=%s, monthly_roi=%s, remaining_principal=%s WHERE id=%s", 
                              (edit_name, edit_roi, edit_remaining, manage_loan_id))
                st.success("Loan updated successfully!")
                st.rerun()
        
        st.write("**Delete Loan**")
        if st.button("Delete Loan Permanently", type="primary"):
            execute_query("DELETE FROM payments WHERE loan_id = %s", (manage_loan_id,))
            execute_query("DELETE FROM loans WHERE id = %s", (manage_loan_id,))
            st.success("Loan and all associated payments have been deleted.")
            st.rerun()
    else:
        st.info("No active loans available to manage.")
        
    st.divider()
    st.subheader("System Administration")
    if st.button("Migrate Local Data to Cloud"):
        with st.spinner("Migrating data to Supabase..."):
            migrate_local_to_cloud()

# --- TAB 5: EMAIL REPORTS ---
with tab5:
    st.subheader("Send Upcoming EMI Report")
    st.write("Generate a PDF summary of all active customers and their upcoming EMI payment dates, then email it to **santosh.padwal1@gmail.com**.")
    
    if st.button("📧 Generate PDF & Send Email", type="primary"):
        with st.spinner("Compiling data and securely sending email..."):
            report_data = fetch_data("SELECT customer_name, remaining_principal, monthly_roi, start_date FROM loans WHERE status = 'Active'")
            
            if not report_data.empty:
                # Add calculated columns for the PDF
                report_data['Next EMI Date'] = report_data['start_date'].apply(calc_next_emi)
                report_data['Current EMI'] = report_data['remaining_principal'] * (report_data['monthly_roi'] / 100)
                
                # Sort by earliest upcoming EMI date
                report_data = report_data.sort_values(by='Next EMI Date')
                
                pdf_file_path = generate_pdf(report_data)
                
                # Verify secrets exist before sending
                if "EMAIL_SENDER" in st.secrets and "EMAIL_PASSWORD" in st.secrets:
                    success = email_report(pdf_file_path)
                    if success:
                        st.success("✅ PDF Generated and successfully emailed to santosh.padwal1@gmail.com!")
                else:
                    st.error("⚠️️ Email configuration missing. Please add EMAIL_SENDER and EMAIL_PASSWORD to your Streamlit Secrets.")
            else:
                st.info("No active loans found. Email not sent.")

# ==========================================
# FOOTER DISCLAIMER
# ==========================================
st.divider()
st.warning("⚠️ **Disclaimer**\n\nThis application is for **educational purposes** only and serves as a **demo**. It is not intended for processing real financial transactions.")
