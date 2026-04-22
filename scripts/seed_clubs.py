import sys
import os

# Add parent directory to sys.path to import database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database

CLUBS = [
    ("ATC", "Altamira Tennis Club"),
    ("CCC", "Caracas Country Club"),
    ("CRC", "Caracas Raquet Club"),
    ("CSC", "Caracas Sport Club"),
    ("CTC", "Caracas Theater Club"),
    ("CAT", "Centre Catala"),
    ("AST", "Centro Asturiano De Caracas"),
    ("POR", "Centro Portugues"),
    ("CIV", "Centro Italiano Venezolano"),
    ("CMC", "Circulo Militar De Caracas"),
    ("CLC", "Club Campestre Los Cortijos"),
    ("HIP", "Club Hipico De Caracas"),
    ("MIR", "Club Miranda"),
    ("CPA", "Club Puerto Azul"),
    ("CSP", "Club Santa Paula"),
    ("TAC", "Club Tachira"),
    ("HEB", "Club Hebraica"),
    ("HGV", "Hermandad Gallega de Venezuela"),
    ("HCV", "Hogar Canario de Venezuela"),
    ("IZC", "Izcaragua Country Club"),
    ("LCC", "Lagunita Country Club"),
    ("MON", "Monte Claro Country Club"),
    ("VAT", "Valle Arriba Athletic Club"),
    ("VAG", "Valle Arriba Golf Club"),
]

def seed():
    print(f"[*] Seeding {len(CLUBS)} clubs into the database...")
    database.init_db()  # Ensure table exists
    for acronym, name in CLUBS:
        database.upsert_club(acronym, name)
        print(f"  [+] {acronym}: {name}")
    print("[*] Seeding complete!")

if __name__ == "__main__":
    seed()
