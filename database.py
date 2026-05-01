"""
CTA Intelligence System — Database (SQLite)
Autor: JDM | #JDMRules
"""

from __future__ import annotations

import sqlite3
import json
from contextlib import contextmanager
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

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


def migrate_schema():
    """Add new columns to existing tables without dropping data."""
    migrations = [
        "ALTER TABLE leagues ADD COLUMN gender TEXT",
        "ALTER TABLE leagues ADD COLUMN level INTEGER",
        "ALTER TABLE leagues ADD COLUMN categoria_name TEXT",
        """CREATE TABLE IF NOT EXISTS groups (
            id             INTEGER PRIMARY KEY,
            league_id      INTEGER REFERENCES leagues(id),
            name           TEXT NOT NULL,
            grupo_num      TEXT NOT NULL,
            categoria_name TEXT
        )""",
        "ALTER TABLE standings ADD COLUMN group_id INTEGER REFERENCES groups(id)",
        "ALTER TABLE matches   ADD COLUMN group_id INTEGER REFERENCES groups(id)",
        """CREATE TABLE IF NOT EXISTS player_match_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id       INTEGER NOT NULL REFERENCES players(id),
            match_date      TEXT,
            opponent_name   TEXT,
            opponent_cta_id INTEGER,
            result          TEXT,
            score           TEXT,
            rubber_type     TEXT,
            partner_name    TEXT,
            scraped_at      TEXT DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_pmh_player ON player_match_history(player_id)",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_pmh_dedup
           ON player_match_history(
             player_id,
             match_date,
             COALESCE(rubber_type, ''),
             COALESCE(opponent_name, '')
           )""",

        # ── Rediseño ctatenis.com 2026-04: nuevos campos ──────────────────
        # Players: foto, club y datos personales (PII)
        "ALTER TABLE players ADD COLUMN photo_url     TEXT",
        "ALTER TABLE players ADD COLUMN club_acronym  TEXT",
        "ALTER TABLE players ADD COLUMN email         TEXT",
        "ALTER TABLE players ADD COLUMN phone         TEXT",
        "ALTER TABLE players ADD COLUMN cedula        TEXT",
        "ALTER TABLE players ADD COLUMN birth_date    TEXT",

        # Player stats: delta, estado, modalidades, chips
        "ALTER TABLE player_stats ADD COLUMN ranking_delta REAL",
        "ALTER TABLE player_stats ADD COLUMN estado        TEXT",
        "ALTER TABLE player_stats ADD COLUMN modalidades   INTEGER",
        "ALTER TABLE player_stats ADD COLUMN chips         TEXT",  # JSON array

        # Teams: liderazgo, protestas y promedios
        "ALTER TABLE teams ADD COLUMN captain_name         TEXT",
        "ALTER TABLE teams ADD COLUMN subcaptain_name      TEXT",
        "ALTER TABLE teams ADD COLUMN captain_player_id    INTEGER",
        "ALTER TABLE teams ADD COLUMN subcaptain_player_id INTEGER",
        "ALTER TABLE teams ADD COLUMN protests_used        INTEGER",
        "ALTER TABLE teams ADD COLUMN protests_total       INTEGER",
        "ALTER TABLE teams ADD COLUMN p_ave                REAL",
        "ALTER TABLE teams ADD COLUMN set_ave              REAL",
        "ALTER TABLE teams ADD COLUMN recent_form          TEXT",  # JSON array ["W","L","W"]

        # Player match history: columnas del historial enriquecido
        "ALTER TABLE player_match_history ADD COLUMN season         TEXT",
        "ALTER TABLE player_match_history ADD COLUMN category_match TEXT",
        "ALTER TABLE player_match_history ADD COLUMN club           TEXT",
        "ALTER TABLE player_match_history ADD COLUMN vs_club        TEXT",
        "ALTER TABLE player_match_history ADD COLUMN ranking_after  REAL",
        "ALTER TABLE player_match_history ADD COLUMN jornada        TEXT",
        "ALTER TABLE player_match_history ADD COLUMN is_refuerzo    INTEGER DEFAULT 0",

        # Nueva tabla: evolución de ranking por jornada (alimenta sparkline)
        """CREATE TABLE IF NOT EXISTS player_ranking_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id   INTEGER NOT NULL REFERENCES players(id),
            idx         INTEGER NOT NULL,
            jornada     TEXT NOT NULL,
            ranking     REAL NOT NULL,
            season      TEXT,
            scraped_at  TEXT DEFAULT (datetime('now'))
        )""",
        "CREATE INDEX IF NOT EXISTS idx_prh_player ON player_ranking_history(player_id)",
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_prh_dedup
           ON player_ranking_history(
             player_id,
             COALESCE(season,''),
             idx
           )""",
        """CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt          TEXT NOT NULL,
            is_admin      INTEGER NOT NULL DEFAULT 0,
            role          TEXT DEFAULT 'capitania',
            created_at    TEXT DEFAULT (datetime('now')),
            updated_at    TEXT DEFAULT (datetime('now'))
        )""",
        "ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'capitania'",
        "UPDATE users SET role = 'admin' WHERE is_admin = 1",
        "UPDATE users SET role = 'capitania' WHERE is_admin = 0",
        """CREATE TABLE IF NOT EXISTS sessions (
            token      TEXT PRIMARY KEY,
            user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_sessions_user    ON sessions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)",
    ]
    with get_connection() as conn:
        for sql in migrations:
            try:
                conn.execute(sql)
            except Exception:
                pass  # already exists


def init_db():
    """Create all tables if they don't exist."""
    migrate_schema()
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS leagues (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                liga_id        INTEGER NOT NULL,
                categoria_id   INTEGER NOT NULL,
                name           TEXT,
                gender         TEXT,
                level          INTEGER,
                categoria_name TEXT,
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

            CREATE TABLE IF NOT EXISTS clubs (
                acronym      TEXT PRIMARY KEY,
                name         TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_standings_team ON standings(team_id);
            CREATE INDEX IF NOT EXISTS idx_standings_scraped ON standings(scraped_at);
            CREATE INDEX IF NOT EXISTS idx_players_team ON players(team_id);
            CREATE INDEX IF NOT EXISTS idx_player_stats_player ON player_stats(player_id);
            CREATE INDEX IF NOT EXISTS idx_matches_home ON matches(home_team_id);
            CREATE INDEX IF NOT EXISTS idx_matches_away ON matches(away_team_id);
            CREATE INDEX IF NOT EXISTS idx_match_rubbers_match ON match_rubbers(match_id);
        """)
    _ensure_admin_user()


# ─────────────────────────────────────────────
# CLUBS
# ─────────────────────────────────────────────
def upsert_club(acronym: str, name: str):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO clubs (acronym, name)
               VALUES (?, ?)
               ON CONFLICT(acronym) DO UPDATE SET name=excluded.name""",
            (acronym.upper(), name),
        )


def get_club_by_acronym(acronym: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM clubs WHERE acronym=?", (acronym.upper(),)).fetchone()
        return dict(row) if row else None


def get_all_clubs() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM clubs ORDER BY acronym").fetchall()
        return [dict(r) for r in rows]


# ─────────────────────────────────────────────
# LEAGUES
# ─────────────────────────────────────────────
def upsert_league(
    liga_id: int,
    categoria_id: int,
    name: str = None,
    gender: str = None,
    level: int = None,
    categoria_name: str = None,
) -> int:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO leagues (liga_id, categoria_id, name, gender, level, categoria_name)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(liga_id, categoria_id) DO UPDATE SET
                 name=COALESCE(excluded.name, leagues.name),
                 gender=COALESCE(excluded.gender, leagues.gender),
                 level=COALESCE(excluded.level, leagues.level),
                 categoria_name=COALESCE(excluded.categoria_name, leagues.categoria_name)""",
            (liga_id, categoria_id, name, gender, level, categoria_name),
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
# GROUPS
# ─────────────────────────────────────────────
def upsert_group(group_id: int, league_id: int, name: str, grupo_num: str, categoria_name: str = None):
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO groups (id, league_id, name, grupo_num, categoria_name)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 league_id=COALESCE(excluded.league_id, groups.league_id),
                 name=excluded.name,
                 grupo_num=excluded.grupo_num,
                 categoria_name=COALESCE(excluded.categoria_name, groups.categoria_name)""",
            (group_id, league_id, name, grupo_num, categoria_name),
        )


def get_groups_by_categoria(categoria_name: str) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT g.* FROM groups g
               WHERE g.categoria_name = ?
               ORDER BY CAST(g.grupo_num AS INTEGER)""",
            (categoria_name,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_group_fixtures(group_id: int) -> list[dict]:
    """Partidos de un grupo, con nombres de equipos, ordenados por jornada y fecha."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT m.id, m.match_date, m.home_score, m.away_score, m.status,
                      ht.name as home_team, ht.cta_id as home_cta_id,
                      at.name as away_team, at.cta_id as away_cta_id,
                      m.raw_detail
               FROM matches m
               JOIN teams ht ON m.home_team_id = ht.id
               JOIN teams at ON m.away_team_id = at.id
               WHERE m.group_id = ?
               ORDER BY m.match_date NULLS LAST, m.id""",
            (group_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_group_standings(group_id: int) -> list[dict]:
    """Última snapshot de standings para un grupo específico."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT s.*, t.name as team_name, t.cta_id as team_cta_id
               FROM standings s
               JOIN teams t ON s.team_id = t.id
               WHERE s.group_id = ?
                 AND s.id = (
                     SELECT MAX(s2.id) FROM standings s2
                     WHERE s2.team_id = s.team_id AND s2.group_id = ?
                 )
               ORDER BY s.position""",
            (group_id, group_id),
        ).fetchall()
        return [dict(r) for r in rows]


def get_team_group_rivals(team_cta_id: int) -> list[dict]:
    """Retorna todos los equipos del mismo grupo que team_cta_id, excluyéndolo."""
    with get_connection() as conn:
        row = conn.execute(
            """SELECT s.group_id FROM standings s
               JOIN teams t ON s.team_id = t.id
               WHERE t.cta_id = ?
               ORDER BY s.id DESC LIMIT 1""",
            (team_cta_id,),
        ).fetchone()
        if not row:
            return []
        group_id = row["group_id"]
        rows = conn.execute(
            """SELECT DISTINCT t.cta_id, t.name, l.categoria_name
               FROM standings s
               JOIN teams t ON s.team_id = t.id
               LEFT JOIN leagues l ON t.league_id = l.id
               WHERE s.group_id = ? AND t.cta_id != ?
               ORDER BY t.name""",
            (group_id, team_cta_id),
        ).fetchall()
        return [dict(r) for r in rows]


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


def search_teams(
    query: str | None = None,
    category: str | None = None,
    gender: str | None = None,
) -> list[dict]:
    """Busca equipos por nombre (LIKE) con filtros opcionales de categoría y género."""
    sql = """
        SELECT t.*, l.categoria_name, l.gender AS league_gender
        FROM teams t
        LEFT JOIN leagues l ON t.league_id = l.id
        WHERE 1=1
    """
    params: list = []
    if query:
        sql += " AND t.name LIKE ?"
        params.append(f"%{query}%")
    if category:
        sql += " AND l.categoria_name LIKE ?"
        params.append(f"%{category}%")
    if gender:
        sql += " AND l.gender = ?"
        params.append(gender.upper())
    sql += " ORDER BY t.name"
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_own_team() -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM teams WHERE is_own_team=1").fetchone()
        return dict(row) if row else None


def get_team_matches(cta_id: int) -> list[dict]:
    """Todos los partidos de un equipo (local o visitante), con nombres."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT m.id, m.match_date, m.home_score, m.away_score, m.status,
                      ht.name as home_team, ht.cta_id as home_cta_id,
                      at.name as away_team, at.cta_id as away_cta_id,
                      m.raw_detail
               FROM matches m
               JOIN teams ht ON m.home_team_id = ht.id
               JOIN teams at ON m.away_team_id = at.id
               WHERE ht.cta_id = ? OR at.cta_id = ?
               ORDER BY m.match_date NULLS LAST, m.id""",
            (cta_id, cta_id),
        ).fetchall()
        return [dict(r) for r in rows]


# Campos escribibles en upsert_team_meta (whitelist defensiva)
_TEAM_META_COLS = {
    "captain_name", "subcaptain_name",
    "captain_player_id", "subcaptain_player_id",
    "protests_used", "protests_total",
    "p_ave", "set_ave",
    "recent_form",
}


def upsert_team_meta(team_id: int, **fields) -> None:
    """Actualiza campos meta del equipo (capitán, protestas, promedios, forma)."""
    cols, vals = [], []
    for k, v in fields.items():
        if k in _TEAM_META_COLS:
            cols.append(f"{k}=?")
            vals.append(v)
    if not cols:
        return
    vals.append(team_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE teams SET {', '.join(cols)}, updated_at=datetime('now') WHERE id=?", vals)


# ─────────────────────────────────────────────
# STANDINGS
# ─────────────────────────────────────────────
def insert_standings(team_id: int, data: dict, group_id: int = None) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO standings
               (team_id, position, played, won, lost, sets_won, sets_lost,
                games_won, games_lost, points, group_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                group_id,
            ),
        )
        return cur.lastrowid


def get_latest_standings(league_id: int = None) -> list[dict]:
    """Get the most recent standings snapshot for each team."""
    with get_connection() as conn:
        if league_id:
            # For a specific league/category: only include group-page rows
            # (sets_won IS NOT NULL) so the table reflects real group standings.
            query = """
                SELECT s.*, t.name as team_name, t.cta_id as team_cta_id
                FROM standings s
                JOIN teams t ON s.team_id = t.id
                WHERE s.id = (
                    SELECT MAX(s2.id) FROM standings s2
                    WHERE s2.team_id = s.team_id
                )
                AND s.sets_won IS NOT NULL
                AND t.league_id = ?
                ORDER BY s.position
            """
            rows = conn.execute(query, (league_id,)).fetchall()
        else:
            # "Todas": show every team that has any standings record,
            # ordered by points descending so the best teams appear first.
            query = """
                SELECT s.*, t.name as team_name, t.cta_id as team_cta_id,
                       l.categoria_name
                FROM standings s
                JOIN teams t ON s.team_id = t.id
                LEFT JOIN leagues l ON t.league_id = l.id
                WHERE s.id = (
                    SELECT MAX(s2.id) FROM standings s2
                    WHERE s2.team_id = s.team_id
                )
                ORDER BY COALESCE(s.points, 0) DESC, COALESCE(s.won, 0) DESC
            """
            rows = conn.execute(query).fetchall()
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


_PLAYER_META_COLS = {
    "photo_url", "club_acronym",
    "email", "phone", "cedula", "birth_date",
}


def upsert_player_meta(player_id: int, **fields) -> None:
    """Actualiza campos meta del jugador (foto, contacto, identidad)."""
    cols, vals = [], []
    for k, v in fields.items():
        if k in _PLAYER_META_COLS and v is not None:
            cols.append(f"{k}=?")
            vals.append(v)
    if not cols:
        return
    vals.append(player_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE players SET {', '.join(cols)}, updated_at=datetime('now') WHERE id=?", vals)


def get_player_by_name_in_team(name: str, team_id: int) -> dict | None:
    """Busca un jugador por nombre dentro de un equipo. Matching case-insensitive."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM players WHERE team_id=? AND lower(name)=lower(?)",
            (team_id, name),
        ).fetchone()
        return dict(row) if row else None


# ─────────────────────────────────────────────
# PLAYER STATS
# ─────────────────────────────────────────────
def insert_player_stats(player_id: int, stats: dict) -> int:
    chips = stats.get("chips")
    if isinstance(chips, list):
        chips = json.dumps(chips, ensure_ascii=False)
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO player_stats
               (player_id, ranking, matches_won, matches_lost,
                sets_won, sets_lost, games_won, games_lost, raw_data,
                ranking_delta, estado, modalidades, chips)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                stats.get("ranking_delta"),
                stats.get("estado"),
                stats.get("modalidades"),
                chips,
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
# PLAYER MATCH HISTORY
# ─────────────────────────────────────────────
def upsert_player_match_history(player_id: int, matches: list) -> None:
    with get_connection() as conn:
        for m in matches:
            # Usa INSERT OR REPLACE para que los campos nuevos (season, club, vs_club,
            # ranking_after, jornada, is_refuerzo) se actualicen en filas legacy.
            existing = conn.execute(
                """SELECT id FROM player_match_history
                   WHERE player_id=? AND COALESCE(match_date,'')=?
                     AND COALESCE(rubber_type,'')=? AND COALESCE(opponent_name,'')=?""",
                (
                    player_id,
                    m.get("match_date") or "",
                    m.get("rubber_type") or "",
                    m.get("opponent_name") or "",
                ),
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE player_match_history SET
                         opponent_cta_id=COALESCE(?, opponent_cta_id),
                         result=COALESCE(?, result),
                         score=COALESCE(?, score),
                         partner_name=COALESCE(?, partner_name),
                         season=COALESCE(?, season),
                         category_match=COALESCE(?, category_match),
                         club=COALESCE(?, club),
                         vs_club=COALESCE(?, vs_club),
                         ranking_after=COALESCE(?, ranking_after),
                         jornada=COALESCE(?, jornada),
                         is_refuerzo=COALESCE(?, is_refuerzo)
                       WHERE id=?""",
                    (
                        m.get("opponent_cta_id"),
                        m.get("result"),
                        m.get("score"),
                        m.get("partner_name"),
                        m.get("season"),
                        m.get("category_match"),
                        m.get("club"),
                        m.get("vs_club"),
                        m.get("ranking_after"),
                        m.get("jornada"),
                        1 if m.get("is_refuerzo") else 0 if m.get("is_refuerzo") is not None else None,
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO player_match_history
                       (player_id, match_date, opponent_name, opponent_cta_id,
                        result, score, rubber_type, partner_name,
                        season, category_match, club, vs_club,
                        ranking_after, jornada, is_refuerzo)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        player_id,
                        m.get("match_date"),
                        m.get("opponent_name"),
                        m.get("opponent_cta_id"),
                        m.get("result"),
                        m.get("score"),
                        m.get("rubber_type"),
                        m.get("partner_name"),
                        m.get("season"),
                        m.get("category_match"),
                        m.get("club"),
                        m.get("vs_club"),
                        m.get("ranking_after"),
                        m.get("jornada"),
                        1 if m.get("is_refuerzo") else 0,
                    ),
                )


# ─────────────────────────────────────────────
# PLAYER RANKING HISTORY (evolución de ranking por jornada)
# ─────────────────────────────────────────────
def replace_player_ranking_history(player_id: int, entries: list, season: str | None = None) -> None:
    """Reemplaza la evolución de ranking del jugador con el nuevo array.
    entries: [{jornada, ranking, season?}] — idx se asigna por orden.
    Borra las entradas previas del mismo (player_id, season) antes de insertar.
    """
    if not entries:
        return
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM player_ranking_history WHERE player_id=? AND COALESCE(season,'')=?",
            (player_id, season or ""),
        )
        for idx, e in enumerate(entries):
            conn.execute(
                """INSERT INTO player_ranking_history
                   (player_id, idx, jornada, ranking, season)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    player_id,
                    idx,
                    e.get("jornada"),
                    e.get("ranking"),
                    e.get("season") or season,
                ),
            )


def get_player_ranking_history(player_cta_id: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT prh.jornada, prh.ranking, prh.season, prh.idx
               FROM player_ranking_history prh
               JOIN players p ON prh.player_id = p.id
               WHERE p.cta_id = ?
               ORDER BY prh.season, prh.idx""",
            (player_cta_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_player_history(player_cta_id: int, limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT pmh.* FROM player_match_history pmh
               JOIN players p ON pmh.player_id = p.id
               WHERE p.cta_id = ?
               ORDER BY pmh.match_date DESC, pmh.id DESC LIMIT ?""",
            (player_cta_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_team_by_player(player_cta_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT t.*, l.categoria_name, l.gender
               FROM teams t
               JOIN players p ON p.team_id = t.id
               LEFT JOIN leagues l ON t.league_id = l.id
               WHERE p.cta_id = ?""",
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
    group_id: int = None,
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
                   raw_detail=?, group_id=COALESCE(?, group_id),
                   scraped_at=datetime('now')
                   WHERE id=?""",
                (home_score, away_score, status, raw_json, group_id, existing["id"]),
            )
            return existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO matches
                   (home_team_id, away_team_id, match_date, home_score,
                    away_score, status, raw_detail, group_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (home_team_id, away_team_id, match_date, home_score,
                 away_score, status, raw_json, group_id),
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


def get_match_details(match_id: int) -> dict | None:
    """Get match header + rubbers from player_match_history.
    Rubbers deduplicated to home-team perspective.
    Returns dict with 'match' (header) and 'rubbers' (list).
    Returns None if match not found; rubbers=[] if no data found.
    """
    with get_connection() as conn:
        # Step 1: Get match header
        match_row = conn.execute(
            """SELECT m.id, m.match_date, m.home_score, m.away_score, m.status, m.raw_detail,
                      ht.name as home_team_name, ht.cta_id as home_team_cta_id,
                      at.name as away_team_name, at.cta_id as away_team_cta_id
               FROM matches m
               JOIN teams ht ON m.home_team_id = ht.id
               JOIN teams at ON m.away_team_id = at.id
               WHERE m.id = ?""",
            (match_id,),
        ).fetchone()

        if not match_row:
            return None

        match_dict = dict(match_row)

        # Extract jornada and fixture_id from raw_detail JSON
        import json
        raw_detail = match_dict.get("raw_detail")
        jornada = None
        fixture_id = None
        if raw_detail:
            try:
                detail_obj = json.loads(raw_detail)
                jornada = detail_obj.get("jornada")
                fixture_id = detail_obj.get("fixture_id")
            except (json.JSONDecodeError, TypeError):
                pass

        match_dict["jornada"] = jornada
        match_dict["fixture_id"] = fixture_id

        return {
            "match": {k: v for k, v in match_dict.items() if k != "raw_detail"},
        }


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


def get_rubber_count_for_match(match_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM match_rubbers WHERE match_id = ?",
            (match_id,),
        ).fetchone()
        return int(row["c"]) if row else 0


def get_rubbers_for_match(match_id: int) -> list[dict]:
    """Return rubbers for a single match in the shape the frontend expects:
       {position, type, home_players:[{name,profile_id}], away_players:[...],
        score, winner}.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT mr.position, mr.rubber_type AS type, mr.score, mr.winner,
                      hp.name AS home_player_name,   hp.cta_id AS home_player_cta,
                      ap.name AS away_player_name,   ap.cta_id AS away_player_cta,
                      hpp.name AS home_partner_name, hpp.cta_id AS home_partner_cta,
                      app.name AS away_partner_name, app.cta_id AS away_partner_cta
               FROM match_rubbers mr
               LEFT JOIN players hp  ON mr.home_player_id  = hp.id
               LEFT JOIN players ap  ON mr.away_player_id  = ap.id
               LEFT JOIN players hpp ON mr.home_partner_id = hpp.id
               LEFT JOIN players app ON mr.away_partner_id = app.id
               WHERE mr.match_id = ?
               ORDER BY mr.position ASC""",
            (match_id,),
        ).fetchall()

        out: list[dict] = []
        for r in rows:
            home_players = []
            if r["home_player_name"]:
                home_players.append({"name": r["home_player_name"], "profile_id": r["home_player_cta"]})
            if r["home_partner_name"]:
                home_players.append({"name": r["home_partner_name"], "profile_id": r["home_partner_cta"]})
            away_players = []
            if r["away_player_name"]:
                away_players.append({"name": r["away_player_name"], "profile_id": r["away_player_cta"]})
            if r["away_partner_name"]:
                away_players.append({"name": r["away_partner_name"], "profile_id": r["away_partner_cta"]})
            out.append({
                "position":     r["position"],
                "type":         r["type"],
                "home_players": home_players,
                "away_players": away_players,
                "score":        r["score"] or "",
                "winner":       r["winner"],
            })
        return out


def get_rubbers_by_team(team_cta_id: int, last_n: int | None = None) -> list[dict]:
    """Return rubbers for matches involving the team, ordered by match_date DESC.

    Each row includes:
      - rubber columns (id, match_id, position, rubber_type, home/away player ids,
        score, winner)
      - match metadata: match_date, home_team_cta_id, away_team_cta_id, status,
        raw_detail (raw JSON, parsed externally)
      - resolved player names: home_player_name, away_player_name,
        home_partner_name, away_partner_name
      - perspective: 'home' or 'away' relative to team_cta_id

    `last_n` limits the number of distinct matches considered (not rubbers).
    """
    with get_connection() as conn:
        if last_n:
            match_rows = conn.execute(
                """SELECT m.id FROM matches m
                   JOIN teams ht ON m.home_team_id = ht.id
                   JOIN teams at ON m.away_team_id = at.id
                   WHERE ht.cta_id = ? OR at.cta_id = ?
                   ORDER BY m.match_date DESC LIMIT ?""",
                (team_cta_id, team_cta_id, last_n),
            ).fetchall()
            match_ids = [r["id"] for r in match_rows]
            if not match_ids:
                return []
            placeholders = ",".join("?" * len(match_ids))
            rows = conn.execute(
                f"""SELECT mr.*, m.match_date, m.status, m.raw_detail,
                          ht.cta_id AS home_team_cta_id,
                          at.cta_id AS away_team_cta_id,
                          hp.name AS home_player_name,
                          ap.name AS away_player_name,
                          hpp.name AS home_partner_name,
                          app.name AS away_partner_name,
                          hp.cta_id AS home_player_cta_id,
                          ap.cta_id AS away_player_cta_id,
                          hpp.cta_id AS home_partner_cta_id,
                          app.cta_id AS away_partner_cta_id
                   FROM match_rubbers mr
                   JOIN matches m ON mr.match_id = m.id
                   JOIN teams ht ON m.home_team_id = ht.id
                   JOIN teams at ON m.away_team_id = at.id
                   LEFT JOIN players hp  ON mr.home_player_id  = hp.id
                   LEFT JOIN players ap  ON mr.away_player_id  = ap.id
                   LEFT JOIN players hpp ON mr.home_partner_id = hpp.id
                   LEFT JOIN players app ON mr.away_partner_id = app.id
                   WHERE m.id IN ({placeholders})
                   ORDER BY m.match_date DESC, mr.position ASC""",
                match_ids,
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT mr.*, m.match_date, m.status, m.raw_detail,
                          ht.cta_id AS home_team_cta_id,
                          at.cta_id AS away_team_cta_id,
                          hp.name AS home_player_name,
                          ap.name AS away_player_name,
                          hpp.name AS home_partner_name,
                          app.name AS away_partner_name,
                          hp.cta_id AS home_player_cta_id,
                          ap.cta_id AS away_player_cta_id,
                          hpp.cta_id AS home_partner_cta_id,
                          app.cta_id AS away_partner_cta_id
                   FROM match_rubbers mr
                   JOIN matches m ON mr.match_id = m.id
                   JOIN teams ht ON m.home_team_id = ht.id
                   JOIN teams at ON m.away_team_id = at.id
                   LEFT JOIN players hp  ON mr.home_player_id  = hp.id
                   LEFT JOIN players ap  ON mr.away_player_id  = ap.id
                   LEFT JOIN players hpp ON mr.home_partner_id = hpp.id
                   LEFT JOIN players app ON mr.away_partner_id = app.id
                   WHERE ht.cta_id = ? OR at.cta_id = ?
                   ORDER BY m.match_date DESC, mr.position ASC""",
                (team_cta_id, team_cta_id),
            ).fetchall()

        out: list[dict] = []
        for row in rows:
            d = dict(row)
            d["perspective"] = "home" if d.get("home_team_cta_id") == team_cta_id else "away"
            out.append(d)
        return out


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


# ─────────────────────────────────────────────
# AUTH: Usuarios y sesiones
# ─────────────────────────────────────────────

def _hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'),
        bytes.fromhex(salt), iterations=260_000,
    )
    return dk.hex()


def _ensure_admin_user():
    with get_connection() as conn:
        if conn.execute("SELECT id FROM users WHERE username='admin'").fetchone():
            return
        salt = secrets.token_hex(32)
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, is_admin) VALUES (?,?,?,1)",
            ("admin", _hash_password(config.ADMIN_PASSWORD, salt), salt),
        )


def verify_user(username: str, password: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        return None
    return dict(row) if _hash_password(password, row["salt"]) == row["password_hash"] else None


def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?,?,?)",
            (token, user_id, expires),
        )
    return token


def get_session_user(token: str | None) -> dict | None:
    if not token:
        return None
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT u.id, u.username, u.is_admin, u.role FROM sessions s JOIN users u ON s.user_id=u.id WHERE s.token=? AND s.expires_at>?",
            (token, now),
        ).fetchone()
    return dict(row) if row else None


def delete_session(token: str):
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))


def get_all_users() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, username, is_admin, role, created_at, updated_at FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_user_by_id(user_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, username, is_admin, role, created_at FROM users WHERE id=?", (user_id,)
        ).fetchone()
    return dict(row) if row else None


def create_user(username: str, password: str, role: str = 'capitania') -> dict:
    salt = secrets.token_hex(32)
    is_admin = 1 if role == 'admin' else 0
    with get_connection() as conn:
        try:
            conn.execute(
                "INSERT INTO users (username, password_hash, salt, is_admin, role) VALUES (?,?,?,?,?)",
                (username, _hash_password(password, salt), salt, is_admin, role),
            )
            row = conn.execute(
                "SELECT id, username, is_admin, role, created_at FROM users WHERE username=?", (username,)
            ).fetchone()
            return dict(row)
        except Exception as exc:
            raise ValueError(f"Username '{username}' ya existe") from exc


def update_user(user_id: int, username: str | None = None,
                password: str | None = None, role: str | None = None):
    with get_connection() as conn:
        if username is not None:
            conn.execute(
                "UPDATE users SET username=?, updated_at=datetime('now') WHERE id=?",
                (username, user_id),
            )
        if password is not None:
            salt = secrets.token_hex(32)
            conn.execute(
                "UPDATE users SET password_hash=?, salt=?, updated_at=datetime('now') WHERE id=?",
                (_hash_password(password, salt), salt, user_id),
            )
        if role is not None:
            is_admin = 1 if role == 'admin' else 0
            conn.execute(
                "UPDATE users SET role=?, is_admin=?, updated_at=datetime('now') WHERE id=?",
                (role, is_admin, user_id),
            )


def delete_user(user_id: int):
    with get_connection() as conn:
        conn.execute("DELETE FROM users WHERE id=?", (user_id,))
