"""Generate realistic sample legal PDF documents for testing LegalLens."""

import os
from pathlib import Path
import fitz  # PyMuPDF


def create_sample_employment_agreement(output_path: Path):
    """Create a realistic 3-page employment agreement with clauses of concern."""
    doc = fitz.open()

    # Page 1: Title & Key Terms
    page1 = doc.new_page(width=595, height=842)
    p1_text = """EMPLOYMENT AGREEMENT

This Employment Agreement ("Agreement") is entered into as of January 15, 2026, by and between Apex Technologies Inc., a Delaware corporation ("Employer"), and Alex Morgan ("Employee").

RECITALS
WHEREAS, Employer desires to employ Employee, and Employee desires to be employed by Employer, upon the terms and conditions set forth herein.

1. POSITION AND DUTIES
1.1 Position: Employee shall serve as Senior Software Architect reporting to the VP of Engineering.
1.2 Full-Time Commitment: Employee agrees to devote full business time, attention, and efforts to the performance of duties for Employer. Employee shall not engage in any other business activity or consulting without prior written approval.
1.3 Location: Initial employment location is Seattle, WA, with remote work permitted subject to manager discretion and company policy.

2. COMPENSATION AND BENEFITS
2.1 Base Salary: Employer shall pay Employee a base salary of $165,000 per annum, payable in semi-monthly installments in accordance with standard payroll practices.
2.2 Discretionary Bonus: Employee may be eligible for an annual performance bonus of up to 20% of base salary, determined at the sole discretion of the Board of Directors.
2.3 Benefits: Employee shall be entitled to participate in all health, dental, vision, retirement (401k with 4% match), and other employee benefit plans maintained by Employer.
2.4 Paid Time Off: Employee is granted 20 days of paid time off (PTO) annually, accrued pro rata per pay period. Maximum PTO rollover is 5 days per calendar year.
"""
    page1.insert_text(fitz.Point(50, 60), p1_text, fontsize=10, fontname="helv")

    # Page 2: IP, Non-Compete, Confidentiality
    page2 = doc.new_page(width=595, height=842)
    p2_text = """3. INTELLECTUAL PROPERTY & INVENTIONS ASSIGNMENT
3.1 Definition of Inventions: "Inventions" means any inventions, designs, algorithms, code, works of authorship, and know-how created, authored, or conceived by Employee during the term of employment.
3.2 Assignment of Inventions: Employee hereby irrevocably assigns to Employer all right, title, and interest worldwide in and to all Inventions, whether made solely or jointly, that (a) relate to Employer's actual or demonstrably anticipated business, (b) result from any work performed for Employer, or (c) use Employer's equipment, supplies, facility, or trade secrets.
3.3 Prior Inventions: All inventions made prior to employment are excluded and listed on Exhibit A.

4. RESTRICTIVE COVENANTS
4.1 Non-Competition: During the term of employment and for a period of twelve (12) months following termination of employment for any reason, Employee shall not directly or indirectly engage in, perform services for, consult with, or invest in any business entity that competes directly with Employer within North America and Europe.
4.2 Non-Solicitation of Employees: For a period of eighteen (18) months following termination, Employee shall not solicit, recruit, or encourage any employee or contractor of Employer to terminate their relationship with Employer.
4.3 Non-Solicitation of Clients: For a period of twelve (12) months following termination, Employee shall not solicit any client, vendor, or partner of Employer with whom Employee had contact during the prior twelve months.
4.4 Confidentiality: Employee shall protect Employer's proprietary and confidential information indefinitely, surviving any termination of this Agreement.
"""
    page2.insert_text(fitz.Point(50, 60), p2_text, fontsize=10, fontname="helv")

    # Page 3: Termination, Dispute Resolution & Signatures
    page3 = doc.new_page(width=595, height=842)
    p3_text = """5. TERM AND TERMINATION
5.1 At-Will Employment: Employment is at-will. Either party may terminate this employment relationship at any time, with or without cause, upon thirty (30) days written notice.
5.2 Termination for Cause: Employer may terminate employment immediately without advance notice or severance in cases of willful misconduct, gross negligence, criminal indictment, or material breach of this Agreement.
5.3 Severance: Upon termination without Cause by Employer, Employee shall receive two (2) months of base salary continuation and COBRA subsidy, conditioned upon execution of a full general release of claims.

6. DISPUTE RESOLUTION & GOVERNING LAW
6.1 Mandatory Arbitration: Any dispute, claim, or controversy arising out of or relating to this Agreement or employment shall be settled by binding individual arbitration administered by JAMS in Seattle, Washington, under its Employment Arbitration Rules.
6.2 Waiver of Class Action: Employee expressly waives any right to assert any claim as a member of a class or collective action against Employer.
6.3 Governing Law: This Agreement shall be governed by and construed in accordance with the laws of the State of Washington, without regard to conflict of laws principles.
6.4 Entire Agreement: This Agreement constitutes the complete and exclusive agreement between the parties concerning its subject matter and supersedes all prior oral or written agreements.

IN WITNESS WHEREOF, the parties have executed this Agreement as of the date first written above.

APEX TECHNOLOGIES INC.                 EMPLOYEE

By: _________________________          By: _________________________
Name: Sarah Jenkins                     Name: Alex Morgan
Title: Chief Executive Officer          Date: January 15, 2026
"""
    page3.insert_text(fitz.Point(50, 60), p3_text, fontsize=10, fontname="helv")

    doc.save(str(output_path))
    doc.close()
    print(f"Generated: {output_path}")


def create_sample_nda_versions(output_dir: Path):
    """Create two versions of an NDA for comparison testing."""
    # Version 1 (Standard Mutual NDA)
    doc_v1 = fitz.open()
    p1 = doc_v1.new_page(width=595, height=842)
    v1_text = """MUTUAL NON-DISCLOSURE AGREEMENT (v1.0)

This Mutual Non-Disclosure Agreement ("Agreement") is dated February 1, 2026, between Vertex Systems LLC ("Party A") and Horizon Labs Inc. ("Party B").

1. PURPOSE
The parties wish to explore a potential business collaboration regarding enterprise cloud infrastructure ("Purpose").

2. CONFIDENTIAL INFORMATION
"Confidential Information" refers to any proprietary information marked as confidential or that reasonably should be understood to be confidential, disclosed by either party to the other.

3. OBLIGATIONS
Each party agrees:
(a) To hold Confidential Information in strict confidence using at least reasonable care.
(b) To use Confidential Information solely for the Purpose.
(c) Not to disclose Confidential Information to any third party without prior written consent.
(d) Confidentiality obligations shall last for a period of three (3) years from the date of disclosure.

4. EXCLUSIONS
Confidential Information does not include information that:
(a) Is or becomes publicly known through no breach of this Agreement.
(b) Was already known to the receiving party prior to disclosure.
(c) Is independently developed without reference to the disclosing party's information.

5. TERMINATION AND RETURN
Either party may terminate discussions at any time with thirty (30) days notice. Upon written request, all Confidential Information shall be returned or destroyed within fourteen (14) days.

6. GOVERNING LAW
This Agreement is governed by the laws of the State of Delaware.
"""
    p1.insert_text(fitz.Point(50, 60), v1_text, fontsize=10, fontname="helv")
    v1_path = output_dir / "nda_mutual_v1.pdf"
    doc_v1.save(str(v1_path))
    doc_v1.close()
    print(f"Generated: {v1_path}")

    # Version 2 (Revised Unilateral/Strict NDA)
    doc_v2 = fitz.open()
    p2 = doc_v2.new_page(width=595, height=842)
    v2_text = """NON-DISCLOSURE AGREEMENT (v2.0 - Revised)

This Non-Disclosure Agreement ("Agreement") is dated February 20, 2026, between Vertex Systems LLC ("Discloser") and Horizon Labs Inc. ("Recipient").

1. PURPOSE
The parties wish to explore a potential strategic acquisition of Recipient's technology assets ("Purpose").

2. CONFIDENTIAL INFORMATION
"Confidential Information" refers to all technical, business, financial, and strategic information disclosed by Discloser, whether marked or unmarked, oral or written, including the existence of these discussions.

3. OBLIGATIONS (ONE-WAY STRICT)
Recipient agrees:
(a) To hold Discloser's Confidential Information in strictest confidence using utmost degree of care.
(b) To use Confidential Information solely to evaluate the acquisition.
(c) Not to disclose Confidential Information to any third party or employee without Discloser's express written pre-approval.
(d) Confidentiality obligations shall survive in perpetuity (indefinitely) for trade secrets and five (5) years for general information.
(e) Liquidated Damages: Any unauthorized disclosure shall result in liquidated damages of $250,000 per violation.

4. NON-SOLICITATION
Recipient agrees not to solicit or hire any engineer or manager of Discloser for twenty-four (24) months.

5. TERMINATION AND RETURN
Discloser may terminate discussions immediately without notice. All materials must be certified destroyed within forty-eight (48) hours of demand.

6. GOVERNING LAW AND INJUNCTIVE RELIEF
This Agreement is governed by the laws of New York State. Discloser is entitled to immediate injunctive relief and attorney fees upon breach.
"""
    p2.insert_text(fitz.Point(50, 60), v2_text, fontsize=10, fontname="helv")
    v2_path = output_dir / "nda_strict_v2.pdf"
    doc_v2.save(str(v2_path))
    doc_v2.close()
    print(f"Generated: {v2_path}")


def create_sample_lease_agreement(output_path: Path):
    """Create a residential lease agreement with landlord/tenant clauses."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    text = """RESIDENTIAL LEASE AGREEMENT

This Agreement is made on March 1, 2026, between Oakwood Properties LLC ("Landlord") and Jordan Taylor ("Tenant").

1. PREMISES: Apartment 4B, 742 Evergreen Terrace, Austin, TX 78701.
2. TERM: 12 months beginning April 1, 2026 and ending March 31, 2027.
3. RENT: $2,200 per month, due on the 1st of each month. Late fee of $100 after the 5th day, plus $10/day thereafter.
4. SECURITY DEPOSIT: $2,200 deposited upon signing. Refundable within 30 days of move-out minus lawful deductions.
5. UTILITIES: Tenant pays electric, internet, and gas. Landlord pays water and trash collection.
6. AUTOMATIC RENEWAL: Lease automatically renews month-to-month with a 10% rent increase unless 60 days advance written notice is provided prior to expiration.
7. MAINTENANCE & REPAIRS: Tenant is responsible for the first $150 of any plumbing or appliance repair per incident.
8. ENTRY BY LANDLORD: Landlord may enter premises with 24 hours advance notice, or immediately in emergencies.
9. PET POLICY: One domestic dog under 35 lbs permitted. $500 non-refundable pet fee plus $40/month pet rent.
10. TERMINATION BY TENANT: Early lease termination penalty is equal to two (2) months full rent plus forfeiture of security deposit.
"""
    page.insert_text(fitz.Point(50, 60), text, fontsize=10, fontname="helv")
    doc.save(str(output_path))
    doc.close()
    print(f"Generated: {output_path}")


def main():
    samples_dir = Path(__file__).parent / "samples"
    samples_dir.mkdir(exist_ok=True)

    create_sample_employment_agreement(samples_dir / "employment_agreement.pdf")
    create_sample_nda_versions(samples_dir)
    create_sample_lease_agreement(samples_dir / "residential_lease.pdf")
    print(f"All sample documents generated successfully in {samples_dir}")


if __name__ == "__main__":
    main()
