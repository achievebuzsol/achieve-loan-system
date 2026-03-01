from flask import Flask, render_template, request, redirect, url_for, jsonify
import sqlite3
import os
from datetime import datetime, timedelta
import math

# Initialize Flask app
app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here-change-in-production')

# FORCE DATABASE RESET - Delete old database on startup
db_path = os.environ.get('DATABASE_URL', 'loan_management.db')
if db_path.startswith('/app/data'):
    os.makedirs('/app/data', exist_ok=True)

# Delete old database to force schema update
if os.path.exists(db_path):
    try:
        os.remove(db_path)
        print(f"Deleted old database: {db_path}")
    except:
        pass

class LoanManagementSystem:
    def __init__(self, db_name='loan_management.db'):
        self.db_name = db_name
        self.init_database()
    
    def init_database(self):
        """Initialize the database with required tables"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Clients table - updated for structured address
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS clients (
                client_id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT,
                contact_person TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                street_address TEXT,
                city TEXT,
                parish TEXT,
                rating_score REAL DEFAULT 5.0,
                total_loans INTEGER DEFAULT 0,
                paid_loans INTEGER DEFAULT 0,
                delinquent_loans INTEGER DEFAULT 0,
                created_date DATE DEFAULT CURRENT_DATE
            )
        ''')
        
        # Loans table - updated with installments and processing fee
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS loans (
                loan_id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id INTEGER,
                principal_amount REAL NOT NULL,
                interest_rate REAL NOT NULL,
                loan_term_days INTEGER NOT NULL,
                installments INTEGER DEFAULT 1,
                processing_fee REAL DEFAULT 0,
                start_date DATE NOT NULL,
                due_date DATE NOT NULL,
                total_amount REAL NOT NULL,
                paid_amount REAL DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_date DATE DEFAULT CURRENT_DATE,
                FOREIGN KEY (client_id) REFERENCES clients (client_id)
            )
        ''')
        
        # Payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                loan_id INTEGER,
                amount REAL NOT NULL,
                payment_date DATE NOT NULL,
                payment_method TEXT,
                notes TEXT,
                FOREIGN KEY (loan_id) REFERENCES loans (loan_id)
            )
        ''')
        
        # Notifications table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                loan_id INTEGER,
                notification_type TEXT,
                message TEXT,
                sent_date DATE DEFAULT CURRENT_DATE,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (loan_id) REFERENCES loans (loan_id)
            )
        ''')
        
        conn.commit()
        conn.close()
        print(f"Database initialized: {self.db_name}")
    
    def calculate_interest_rate(self, client_id, base_rate=0.15):
        """Calculate interest rate based on client rating"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('SELECT rating_score FROM clients WHERE client_id = ?', (client_id,))
        result = cursor.fetchone()
        
        if result:
            rating = result[0]
            discount = (rating - 1) * 0.02
            final_rate = max(base_rate - discount, base_rate * 0.75)
        else:
            final_rate = base_rate
        
        conn.close()
        return final_rate
    
    def create_client(self, company_name, contact_person, email, phone, street_address, city, parish):
        """Add a new client to the system"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO clients (company_name, contact_person, email, phone, street_address, city, parish)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (company_name if company_name else None, contact_person, email, phone, street_address, city, parish))
        
        client_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return client_id
    
    def create_loan(self, client_id, principal_amount, interest_rate, loan_term_days, installments=1, processing_fee=0):
        """Create a new loan with custom interest rate, installments and processing fee"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        interest_amount = principal_amount * interest_rate * (loan_term_days / 365)
        total_amount = principal_amount + interest_amount + processing_fee
        
        start_date = datetime.now().date()
        due_date = start_date + timedelta(days=loan_term_days)
        
        cursor.execute('''
            INSERT INTO loans (client_id, principal_amount, interest_rate, loan_term_days, 
                             installments, processing_fee, start_date, due_date, total_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (client_id, principal_amount, interest_rate, loan_term_days, 
              installments, processing_fee, start_date, due_date, total_amount))
        
        loan_id = cursor.lastrowid
        cursor.execute('UPDATE clients SET total_loans = total_loans + 1 WHERE client_id = ?', (client_id,))
        
        conn.commit()
        conn.close()
        
        return loan_id
    
    def make_payment(self, loan_id, amount, payment_method='cash', notes=''):
        """Record a payment"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('SELECT paid_amount, total_amount, client_id FROM loans WHERE loan_id = ?', (loan_id,))
        result = cursor.fetchone()
        
        if result:
            paid_amount, total_amount, client_id = result
            new_paid_amount = paid_amount + amount
            
            cursor.execute('''
                INSERT INTO payments (loan_id, amount, payment_date, payment_method, notes)
                VALUES (?, ?, ?, ?, ?)
            ''', (loan_id, amount, datetime.now().date(), payment_method, notes))
            
            cursor.execute('UPDATE loans SET paid_amount = ? WHERE loan_id = ?', (new_paid_amount, loan_id))
            
            if new_paid_amount >= total_amount:
                cursor.execute('UPDATE loans SET status = "paid" WHERE loan_id = ?', (loan_id,))
                cursor.execute('UPDATE clients SET paid_loans = paid_loans + 1 WHERE client_id = ?', (client_id,))
                self.update_client_rating(client_id)
            
            conn.commit()
        
        conn.close()
    
    def update_client_rating(self, client_id):
        """Update client rating based on payment history"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT COUNT(*) as total_loans, 
                   SUM(CASE WHEN status = 'paid' THEN 1 ELSE 0 END) as paid_loans,
                   SUM(CASE WHEN status = 'delinquent' THEN 1 ELSE 0 END) as delinquent_loans
            FROM loans WHERE client_id = ?
        ''', (client_id,))
        
        result = cursor.fetchone()
        
        if result and result[0] > 0:
            total_loans, paid_loans, delinquent_loans = result
            payment_ratio = paid_loans / total_loans if total_loans > 0 else 0
            
            rating = 5.0
            
            if payment_ratio > 0.8:
                rating += 2.5
            elif payment_ratio > 0.6:
                rating += 1.5
            elif payment_ratio > 0.4:
                rating += 0.5
            
            delinquent_ratio = delinquent_loans / total_loans if total_loans > 0 else 0
            if delinquent_ratio > 0.2:
                rating -= 2.0
            elif delinquent_ratio > 0.1:
                rating -= 1.0
            
            rating = max(1.0, min(10.0, rating))
            
            cursor.execute('UPDATE clients SET rating_score = ? WHERE client_id = ?', (rating, client_id))
            conn.commit()
        
        conn.close()
    
    def check_delinquent_loans(self):
        """Check for delinquent loans and create notifications"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        today = datetime.now().date()
        
        cursor.execute('''
            SELECT loan_id, client_id, due_date, total_amount, paid_amount
            FROM loans 
            WHERE status = 'active' AND due_date < ?
        ''', (today,))
        
        delinquent_loans = cursor.fetchall()
        
        for loan in delinquent_loans:
            loan_id, client_id, due_date, total_amount, paid_amount = loan
            outstanding = total_amount - paid_amount
            days_overdue = (today - due_date).days
            
            cursor.execute('UPDATE loans SET status = "delinquent" WHERE loan_id = ?', (loan_id,))
            
            message = f"Loan #{loan_id} is {days_overdue} days overdue. Outstanding amount: ${outstanding:.2f}"
            
            cursor.execute('''
                INSERT INTO notifications (loan_id, notification_type, message)
                VALUES (?, 'delinquent', ?)
            ''', (loan_id, message))
            
            cursor.execute('UPDATE clients SET delinquent_loans = delinquent_loans + 1 WHERE client_id = ?', (client_id,))
        
        conn.commit()
        conn.close()
        
        return len(delinquent_loans)
    
    def get_loan_summary(self, loan_id):
        """Get detailed loan information"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT l.*, c.company_name, c.contact_person, c.email, c.rating_score
            FROM loans l
            JOIN clients c ON l.client_id = c.client_id
            WHERE l.loan_id = ?
        ''', (loan_id,))
        
        loan_data = cursor.fetchone()
        
        if loan_data:
            columns = [description[0] for description in cursor.description]
            loan_dict = dict(zip(columns, loan_data))
            
            cursor.execute('''
                SELECT * FROM payments WHERE loan_id = ? ORDER BY payment_date DESC
            ''', (loan_id,))
            
            payments = []
            for payment in cursor.fetchall():
                payment_columns = [description[0] for description in cursor.description]
                payments.append(dict(zip(payment_columns, payment)))
            
            loan_dict['payments'] = payments
            loan_dict['outstanding_amount'] = loan_dict['total_amount'] - loan_dict['paid_amount']
            
            conn.close()
            return loan_dict
        
        conn.close()
        return None
    
    def get_dashboard_data(self):
        """Get dashboard statistics"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM clients')
        total_clients = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM loans')
        total_loans = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(principal_amount) FROM loans')
        total_principal = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT SUM(total_amount) FROM loans WHERE status = "paid"')
        total_paid = cursor.fetchone()[0] or 0
        
        cursor.execute('SELECT COUNT(*) FROM loans WHERE status = "active"')
        active_loans = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM loans WHERE status = "delinquent"')
        delinquent_loans = cursor.fetchone()[0]
        
        cursor.execute('''
            SELECT n.*, c.company_name 
            FROM notifications n
            JOIN loans l ON n.loan_id = l.loan_id
            JOIN clients c ON l.client_id = c.client_id
            ORDER BY n.sent_date DESC
            LIMIT 10
        ''')
        
        recent_notifications = []
        for notification in cursor.fetchall():
            columns = [description[0] for description in cursor.description]
            recent_notifications.append(dict(zip(columns, notification)))
        
        conn.close()
        
        return {
            'total_clients': total_clients,
            'total_loans': total_loans,
            'total_principal': total_principal,
            'total_paid': total_paid,
            'active_loans': active_loans,
            'delinquent_loans': delinquent_loans,
            'recent_notifications': recent_notifications
        }

# Initialize the loan management system
lms = LoanManagementSystem(db_name=db_path)

# Flask routes
@app.route('/')
def dashboard():
    dashboard_data = lms.get_dashboard_data()
    return render_template('dashboard.html', data=dashboard_data)

@app.route('/clients')
def clients():
    conn = sqlite3.connect(lms.db_name)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM clients ORDER BY company_name')
    clients_data = cursor.fetchall()
    conn.close()
    return render_template('clients.html', clients=clients_data)

@app.route('/loans')
def loans():
    conn = sqlite3.connect(lms.db_name)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT l.*, c.company_name, c.contact_person
        FROM loans l
        JOIN clients c ON l.client_id = c.client_id
        ORDER BY l.created_date DESC
    ''')
    loans_data = cursor.fetchall()
    conn.close()
    return render_template('loans.html', loans=loans_data)

@app.route('/client/<int:client_id>')
def client_detail(client_id):
    conn = sqlite3.connect(lms.db_name)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM clients WHERE client_id = ?', (client_id,))
    client = cursor.fetchone()
    
    cursor.execute('''
        SELECT * FROM loans WHERE client_id = ? ORDER BY created_date DESC
    ''', (client_id,))
    client_loans = cursor.fetchall()
    
    conn.close()
    return render_template('client_detail.html', client=client, loans=client_loans)

@app.route('/loan/<int:loan_id>')
def loan_detail(loan_id):
    loan_data = lms.get_loan_summary(loan_id)
    return render_template('loan_detail.html', loan=loan_data)

@app.route('/add_client', methods=['GET', 'POST'])
def add_client():
    if request.method == 'POST':
        company_name = request.form.get('company_name')
        contact_person = request.form['contact_person']
        email = request.form['email']
        phone = request.form['phone']
        street_address = request.form.get('street_address')
        city = request.form.get('city')
        parish = request.form['parish']
        
        client_id = lms.create_client(company_name, contact_person, email, phone, street_address, city, parish)
        return redirect(url_for('client_detail', client_id=client_id))
    
    return render_template('add_client.html')

@app.route('/edit_client/<int:client_id>', methods=['GET', 'POST'])
def edit_client(client_id):
    conn = sqlite3.connect(lms.db_name)
    cursor = conn.cursor()
    
    if request.method == 'POST':
        company_name = request.form.get('company_name')
        contact_person = request.form['contact_person']
        email = request.form['email']
        phone = request.form['phone']
        street_address = request.form.get('street_address')
        city = request.form.get('city')
        parish = request.form['parish']
        
        cursor.execute('''
            UPDATE clients 
            SET company_name = ?, contact_person = ?, email = ?, phone = ?, 
                street_address = ?, city = ?, parish = ?
            WHERE client_id = ?
        ''', (company_name if company_name else None, contact_person, email, phone, 
              street_address, city, parish, client_id))
        
        conn.commit()
        conn.close()
        return redirect(url_for('clients'))
    
    cursor.execute('SELECT * FROM clients WHERE client_id = ?', (client_id,))
    client = cursor.fetchone()
    
    # Parse old address format if exists
    address_parts = []
    if client[5]:  # old address field might contain combined data
        address_parts = client[5].split(', ') if ',' in client[5] else [client[5], '', '']
    
    conn.close()
    
    return render_template('edit_client.html', client=client, address_parts=address_parts)

@app.route('/create_loan', methods=['GET', 'POST'])
def create_loan():
    if request.method == 'POST':
        client_id = int(request.form['client_id'])
        principal_amount = float(request.form['principal_amount'])
        interest_rate = float(request.form['interest_rate']) / 100
        loan_term_days = int(request.form['loan_term_days'])
        installments = int(request.form.get('installments', 1))
        processing_fee = float(request.form.get('processing_fee', 0))
        
        loan_id = lms.create_loan(client_id, principal_amount, interest_rate, loan_term_days, installments, processing_fee)
        return redirect(url_for('loan_detail', loan_id=loan_id))
    
    # GET request - fetch clients
    conn = sqlite3.connect(lms.db_name)
    cursor = conn.cursor()
    # Get all clients: id, company_name, contact_person, rating_score
    cursor.execute('SELECT client_id, company_name, contact_person, rating_score FROM clients ORDER BY company_name')
    clients = cursor.fetchall()
    conn.close()
    
    return render_template('create_loan.html', clients=clients)

@app.route('/edit_loan/<int:loan_id>', methods=['GET', 'POST'])
def edit_loan(loan_id):
    conn = sqlite3.connect(lms.db_name)
    cursor = conn.cursor()
    
    if request.method == 'POST':
        principal_amount = float(request.form['principal_amount'])
        interest_rate = float(request.form['interest_rate']) / 100
        loan_term_days = int(request.form['loan_term_days'])
        installments = int(request.form.get('installments', 1))
        processing_fee = float(request.form.get('processing_fee', 0))
        due_date = request.form['due_date']
        
        interest_amount = principal_amount * interest_rate * (loan_term_days / 365)
        total_amount = principal_amount + interest_amount + processing_fee
        
        cursor.execute('''
            UPDATE loans 
            SET principal_amount = ?, interest_rate = ?, loan_term_days = ?, 
                installments = ?, processing_fee = ?, due_date = ?, total_amount = ?
            WHERE loan_id = ?
        ''', (principal_amount, interest_rate, loan_term_days, installments, 
              processing_fee, due_date, total_amount, loan_id))
        
        conn.commit()
        conn.close()
        return redirect(url_for('loans'))
    
    cursor.execute('''
        SELECT l.*, c.company_name 
        FROM loans l
        JOIN clients c ON l.client_id = c.client_id
        WHERE l.loan_id = ?
    ''', (loan_id,))
    loan = cursor.fetchone()
    
    conn.close()
    return render_template('edit_loan.html', loan=loan)

@app.route('/make_payment/<int:loan_id>', methods=['POST'])
def make_payment(loan_id):
    amount = float(request.form['amount'])
    payment_method = request.form['payment_method']
    notes = request.form.get('notes', '')
    
    lms.make_payment(loan_id, amount, payment_method, notes)
    return redirect(url_for('loan_detail', loan_id=loan_id))

@app.route('/api/notifications')
def api_notifications():
    conn = sqlite3.connect(lms.db_name)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT n.*, c.company_name 
        FROM notifications n
        JOIN loans l ON n.loan_id = l.loan_id
        JOIN clients c ON l.client_id = c.client_id
        WHERE n.status = 'pending'
        ORDER BY n.sent_date DESC
    ''')
    
    notifications = []
    for notification in cursor.fetchall():
        columns = [description[0] for description in cursor.description]
        notifications.append(dict(zip(columns, notification)))
    
    conn.close()
    return jsonify(notifications)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)