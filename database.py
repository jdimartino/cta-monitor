"""
CTA Intelligence System — Database (SQLite)
Autor: JDM | #JDMRules
"""

from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime

import config


@contextmanager
def get_connection():
    """Yield a SQLite connection with Row factory. Auto-commits on success."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create all tables if they don't exist."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS leagues (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                liga_id      INTEGER NOT NULL,
                categoria_id INTEGER NOT NULL,
                name         TEXT,
                UNIQUE(liga_id, categoria_id)
            );

            CREATE TABLE IF NOT EXISTS teams (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                cta_id      INTEGER UNIQUE NOT NULL,
                name        TEXT NOT NULL,
                league_id   INTEGER REFERENCES leagues(id),
                is_own_team INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS standings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                team_id     INTEGER NOT NULL REFERENCES teams(id),
                position    INTEGER,
                played      INTEGER,
                won         INTEGER,
                lost        INTEGER,
                sets_won    INTEGER,
                sets_lost   INTEGER,
                games_won   INTEGER,
                games_lost  INTEGER,
                points      INTEGER,
                scraped_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS players (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                cta_id      INTEGER UNIQUE NOT NULL,
                name        TEXT NOT NULL,
                team_id     INTEGER REFERENCES teams(id),
                created_at  TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS player_stats (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id    INTEGER NOT NULL REFERENCES players(id),
                ranking      TEXT,
                matches_won  INTEGER,
                matches_lost INTEGER,
                sets_won     INTEGER,
                sets_lost    INTEGER,
                games_won    INTEGER,
                games_lost   INTEGER,
                raw_data     TEXT,
                scraped_at   TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS matches (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                home_team_id  INTEGER REFERENCES teams(id),
                away_team_id  INTEGER REFERENCES teams(id),
                match_date    TEXT,
                home_score    TEXT,
                away_score    TEXT,
                status        TEXT DEFAULT 'scheduled',
                raw_detail    TEXT,
                scraped_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS match_rubbers (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id        INTEGER NOT NULL REFERENCES matches(id),
                position        INTEGER,
                rubber_type     TEXT,
                home_player_id  INTEGER REFERENCES players(id),
                away_player_id  INTEGER REFERENCES players(id),
                home_partner_id INTEGER REFERENCES players(id),
                away_partner_id INTEGER REFERENCES players(id),
                score           TEXT,
                winner          TEXT
            );

            CREATE TABLE IF NOT EXISTS hashes (
                key         TEXT PRIMARY KEY,
                hash_value  TEXT NOT NULL,
                updated_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS url_map (
                url          TEXT PRIMARY KEY,
                entity_type  TEXT NOT NULL,
                entity_id    INTEGER,
                last_scraped TEXT,
                last_hash    TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_standings_team ON standings(team_id);
            CREATE INDEX IF NOT EXISTS idx_standings_scraped ON standings(scraped_at);
            CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
            CREATE INDEX IF NOT EXISTS idx_player_stats_player ON player_stats(player_id);
            CREATE INDEX IF NOT EXISTS idx_matches_home ON matches(home_team_id);
            CREATE INDEX IF NOT EXISTS idx_matches_away ON matches(away_team_id);
            CREATE INDEX IF NOT EXISTS idx_match_rubbers_match ON match_rubbers(match_id);
        """)


# ─────────────────────────────────────────────
# LEAGUES
# ─────────────────────────────────────────────
def upsert_league(liga_id: int, categoria_id: int, name: str = None) -> int:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO leagues (liga_id, categoria_id, name)
               VALUES (?, ?, ?)
               ON CONFLICT(liga_id, categoria_id) DO UPDATE SET name=excluded.name""",
            (liga_id, categoria_id, name),
        )
        row = conn.execute(
            "SELECT id FROM leagues WHERE liga_id=? AND categoria_id=?",
            (liga_id, categoria_id),
        ).fetchone()
        return row["id"]


def get_league(liga_id: int, categoria_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM leagues WHERE liga_id=? AND categoria_id=?",
            (liga_id, categoria_id),
        ).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────
# TEAMS
# ─────────────────────────────────────────────
def upsert_team(cta_id: int, name: str, league_id: int = None, is_own: bool = False) -> int:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO teams (cta_id, name, league_id, is_own_team, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(cta_id) DO UPDATE SET
                 name=excluded.name,
                 league_id=COALESCE(excluded.league_id, teams.league_id),
                 is_own_team=MAX(teams.is_own_team, excluded.is_own_team),
                 updated_at=datetime('now')""",
            (cta_id, name, league_id, int(is_own)),
        )
        row = conn.execute("SELECT id FROM teams WHERE cta_id=?", (cta_id,)).fetchone()
        return row["id"]


def get_team(cta_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM teams WHERE cta_id=?", (cta_id,)).fetchone()
        return dict(row) if row else None


def get_team_by_id(team_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
        return dict(row) if row else None


def get_all_teams(league_id: int = None) -> list[dict]:
    with get_connection() as conn:
        if league_id:
            rows = conn.execute(
                "SELECT * FROM teams WHERE league_id=? ORDER BY name", (league_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM teams ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_own_team() -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM teams WHERE is_own_team=1").fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────
# STANDINGS
# ─────────────────────────────────────────────
def insert_standings(team_id: int, data: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO standings
               (team_id, position, played, won, lost, sets_won, sets_lost,
                games_won, games_lost, points)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                team_id,
                data.get("position"),
                data.get("played"),
                data.get("won"),
                data.get("lost"),
                data.get("sets_won"),
                data.get("sets_lost"),
                data.get("games_won"),
                data.get("games_lost"),
                data.get("points"),
            ),
        )
        return cur.lastrowid


def get_latest_standings(league_id: int = None) -> list[dict]:
    """Get the most recent standings snapshot for each team."""
    with get_connection() as conn:
        # Only show standings from the group page (sets_won IS NOT NULL).
        # Legacy rows from the general league crawl have sets_won = NULL and
        # are excluded so the table only reflects the real group standings.
        query = """
            SELECT s.*, t.name as team_name, t.cta_id as team_cta_id
            FROM standings s
            JOIN teams t ON s.team_id = t.id
            WHERE s.id = (
                SELECT MAX(s2.id) FROM standings s2
                WHERE s2.team_id = s.team_id
            )
            AND s.sets_won IS NOT NULL
        """
        if league_id:
            query += " AND t.league_id = ?"
            rows = conn.execute(query + " ORDER BY s.position", (league_id,)).fetchall()
        else:
            rows = conn.execute(query + " ORDER BY s.position").fetchall()
        return [dict(r) for r in rows]


def get_team_standings_history(team_cta_id: int, limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT s.* FROM standings s
               JOIN teams t ON s.team_id = t.id
               WHERE t.cta_id = ?
               ORDER BY s.scraped_at DESC LIMIT ?""",
            (team_cta_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# PLAYERS
# ─────────────────────────────────────────────
def upsert_player(cta_id: int, name: str, team_id: int = None) -> int:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO players (cta_id, name, team_id, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(cta_id) DO UPDATE SET
                 name=excluded.name,
                 team_id=COALESCE(excluded.team_id, players.team_id),
                 updated_at=datetime('now')""",
            (cta_id, name, team_id),
        )
        row = conn.execute("SELECT id FROM players WHERE cta_id=?", (cta_id,)).fetchone()
        return row["id"]


def get_player(cta_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM players WHERE cta_id=?", (cta_id,)).fetchone()
        return dict(row) if row else None


def get_team_players(team_cta_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT p.* FROM players p
               JOIN teams t ON p.team_id = t.id
               WHERE t.cta_id = ?
               ORDER BY p.name""",
            (team_cta_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# PLAYER STATS
# ─────────────────────────────────────────────
def insert_player_stats(player_id: int, stats: dict) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO player_stats
               (player_id, ranking, matches_won, matches_lost,
                sets_won, sets_lost, games_won, games_lost, raw_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                player_id,
                stats.get("ranking"),
                stats.get("matches_won"),
                stats.get("matches_lost"),
                stats.get("sets_won"),
                stats.get("sets_lost"),
                stats.get("games_won"),
                stats.get("games_lost"),
                json.dumps(stats.get("raw_data", {}), ensure_ascii=False),
            ),
        )
        return cur.lastrowid


def get_latest_player_stats(player_cta_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT ps.* FROM player_stats ps
               JOIN players p ON ps.player_id = p.id
               WHERE p.cta_id = ?
               ORDER BY ps.scraped_at DESC LIMIT 1""",
            (player_cta_id,),
        ).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────
# MATCHES
# ─────────────────────────────────────────────
def upsert_match(
    home_team_id: int,
    away_team_id: int,
    match_date: str,
    home_score: str = None,
    away_score: str = None,
    status: str = "scheduled",
    raw_detail: dict = None,
) -> int:
    with get_connection() as conn:
        # Check if match already exists (same teams + date)
        existing = conn.execute(
            """SELECT id FROM matches
               WHERE home_team_id=? AND away_team_id=? AND match_date=?""",
            (home_team_id, away_team_id, match_date),
        ).fetchone()

        raw_json = json.dumps(raw_detail, ensure_ascii=False) if raw_detail else None

        if existing:
            conn.execute(
                """UPDATE matches SET home_score=?, away_score=?, status=?,
                   raw_detail=?, scraped_at=datetime('now')
                   WHERE id=?""",
                (home_score, away_score, status, raw_json, existing["id"]),
            )
            return existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO matches
                   (home_team_id, away_team_id, match_date, home_score,
                    away_score, status, raw_detail)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (home_team_id, away_team_id, match_date, home_score,
                 away_score, status, raw_json),
            )
            return cur.lastrowid


def get_team_matches(team_cta_id: int, limit: int = 10) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT m.*,
                      ht.name as home_team_name, ht.cta_id as home_cta_id,
                      at.name as away_team_name, at.cta_id as away_cta_id
               FROM matches m
               JOIN teams ht ON m.home_team_id = ht.id
               JOIN teams at ON m.away_team_id = at.id
               WHERE ht.cta_id = ? OR at.cta_id = ?
               ORDER BY m.match_date DESC LIMIT ?""",
            (team_cta_id, team_cta_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_head_to_head(team_a_cta_id: int, team_b_cta_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT m.*,
                      ht.name as home_team_name, ht.cta_id as home_cta_id,
                      at.name as away_team_name, at.cta_id as away_cta_id
               FROM matches m
               JOIN teams ht ON m.home_team_id = ht.id
               JOIN teams at ON m.away_team_id = at.id
               WHERE (ht.cta_id = ? AND at.cta_id = ?)
                  OR (ht.cta_id = ? AND at.cta_id = ?)
               ORDER BY m.match_date DESC""",
            (team_a_cta_id, team_b_cta_id, team_b_cta_id, team_a_cta_id),
        ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# MATCH RUBBERS
# ─────────────────────────────────────────────
def insert_rubber(
    match_id: int,
    position: int,
    rubber_type: str,
    home_player_id: int = None,
    away_player_id: int = None,
    home_partner_id: int = None,
    away_partner_id: int = None,
    score: str = None,
    winner: str = None,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO match_rubbers
               (match_id, position, rubber_type, home_player_id, away_player_id,
                home_partner_id, away_partner_id, score, winner)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (match_id, position, rubber_type, home_player_id, away_player_id,
             home_partner_id, away_partner_id, score, winner),
        )
        return cur.lastrowid


def get_player_match_history(player_cta_id: int, limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT mr.*, m.match_date, m.status,
                      hp.name as home_player_name, ap.name as away_player_name
               FROM match_rubbers mr
               JOIN matches m ON mr.match_id = m.id
               LEFT JOIN players hp ON mr.home_player_id = hp.id
               LEFT JOIN players ap ON mr.away_player_id = ap.id
               WHERE hp.cta_id = ? OR ap.cta_id = ?
               ORDER BY m.match_date DESC LIMIT ?""",
            (player_cta_id, player_cta_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_player_head_to_head(player_a_cta_id: int, player_b_cta_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT mr.*, m.match_date
               FROM match_rubbers mr
               JOIN matches m ON mr.match_id = m.id
               LEFT JOIN players hp ON mr.home_player_id = hp.id
               LEFT JOIN players ap ON mr.away_player_id = ap.id
               WHERE (hp.cta_id = ? AND ap.cta_id = ?)
                  OR (hp.cta_id = ? AND ap.cta_id = ?)
               ORDER BY m.match_date DESC""",
            (player_a_cta_id, player_b_cta_id, player_b_cta_id, player_a_cta_id),
        ).fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# HASHES (replaces cta_state.json)
# ─────────────────────────────────────────────
def get_hash(key: str) -> str | None:
    with get_connection() as conn:
        row = conn.execute("SELECT hash_value FROM hashes WHERE key=?", (key,)).fetchone()
        return row["hash_value"] if row else None


def set_hash(key: str, value: str):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO hashes (key, hash_value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                 hash_value=excluded.hash_value,
                 updated_at=datetime('now')""",
            (key, value),
        )


# ─────────────────────────────────────────────
# URL MAP
# ─────────────────────────────────────────────
def set_url(url: str, entity_type: str, entity_id: int = None):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO url_map (url, entity_type, entity_id, last_scraped)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(url) DO UPDATE SET
                 entity_type=excluded.entity_type,
                 entity_id=COALESCE(excluded.entity_id, url_map.entity_id),
                 last_scraped=datetime('now')""",
            (url, entity_type, entity_id),
        )


def update_url_hash(url: str, hash_value: str):
    with get_connection() as conn:
        conn.execute(
            """UPDATE url_map SET last_hash=?, last_scraped=datetime('now')
               WHERE url=?""",
            (hash_value, url),
        )


def get_urls_by_type(entity_type: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM url_map WHERE entity_type=?", (entity_type,)
        ).fetchall()
        return [dict(r) for r in rows]


def needs_rescrape(url: str, new_hash: str) -> bool:
    """Returns True if the page content changed or was never scraped."""
    with get_connection() as conn:
        row = conn.execute("SELECT last_hash FROM url_map WHERE url=?", (url,)).fetchone()
        if not row or row["last_hash"] != new_hash:
            return True
        return False


def migrate_legacy_state():
    """Import hashes from cta_state.json if it exists."""
    import os
    state_file = str(config.LEGACY_STATE_FILE)
    if not os.path.exists(state_file):
        return

    try:
        with open(state_file) as f:
            state = json.load(f)
        for key, value in state.items():
            set_hash(f"legacy_{key}", value)
        print(f"[DB] Migrated {len(state)} hashes from cta_state.json")
    except Exception as e:
        print(f"[DB] Warning: Could not migrate legacy state: {e}")
