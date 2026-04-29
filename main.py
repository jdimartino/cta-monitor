#!/usr/bin/env python3
"""
CTA Intelligence System — CLI Principal
Autor: JDM | #JDMRules
Club Táchira 6ta B | Competencias de Tenis Amateur

Uso:
    python main.py crawl [--full]
    python main.py monitor [--force] [--loop N]
    python main.py rival TEAM_ID [--refresh]
    python main.py draw RIVAL_ID
    python main.py report
    python main.py sync
"""

from __future__ import annotations

import logging
import sys

import click

import config
import database


def setup_logging(verbose: bool = False):
    """Configure logging for all modules."""
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)

    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(fmt, datefmt="%H:%M:%S"))

    # File handler
    file_handler = logging.FileHandler(config.LOG_DIR / "cta.log", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(console)
    root.addHandler(file_handler)


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def cli(verbose):
    """CTA Intelligence System — Club Tachira 6ta B"""
    setup_logging(verbose)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    database.init_db()


@cli.command()
@click.option("--full", is_flag=True, help="Full crawl (ignore incremental cache)")
def crawl(full):
    """Indexar todo el sitio: equipos, jugadores, estadisticas."""
    import spider
    import auth

    session = auth.get_session()
    if not session:
        click.echo("Error: No se pudo autenticar. Verifica las credenciales en .env")
        sys.exit(1)

    result = spider.discover_all(session, incremental=not full, max_pages=None if full else config.MAX_PAGES_PER_CRAWL)
    click.echo(f"\nResumen del crawl:")
    click.echo(f"  Equipos encontrados: {result.get('teams_found', 0)}")
    click.echo(f"  Jugadores encontrados: {result.get('players_found', 0)}")
    click.echo(f"  Paginas scrapeadas: {result.get('pages_scraped', 0)}")


@cli.command("monitor")
@click.option("--force", is_flag=True, help="Enviar alertas aunque no haya cambios")
@click.option("--loop", type=int, default=None, help="Repetir cada N segundos")
def monitor_cmd(force, loop):
    """Monitorear cambios y enviar alertas por Telegram."""
    import monitor

    if loop:
        click.echo(f"Modo loop: chequeando cada {loop} segundos...")
        monitor.run_monitor(interval_seconds=loop)
    else:
        monitor.monitor_cycle(force_notify=force)


@cli.command("player")
@click.argument("player_id", type=int)
def crawl_player_cmd(player_id):
    """Crawl un jugador individual por su CTA ID."""
    import spider
    import auth

    session = auth.get_session()
    if not session:
        click.echo("Error: No se pudo autenticar.")
        sys.exit(1)

    click.echo(f"[Player] Scrapeando jugador {player_id}...")
    data = spider.crawl_player(session, player_id)
    click.echo(f"  Nombre: {data.get('name', '?')}")
    click.echo(f"  Ranking: {data.get('ranking', 'N/R')}")
    click.echo(f"  Partidos: {data.get('matches_won', '-')}V / {data.get('matches_lost', '-')}D")
    click.echo(f"  Sets: {data.get('sets_won', '-')} / {data.get('sets_lost', '-')}")
    click.echo(f"  Juegos: {data.get('games_won', '-')} / {data.get('games_lost', '-')}")
    click.echo(f"  Historial: {len(data.get('match_history', []))} partidos")


@cli.command()
@click.argument("team_id", type=int)
@click.option("--refresh", is_flag=True, help="Re-crawl datos del equipo antes de analizar")
def rival(team_id, refresh):
    """Analizar un equipo rival dado su TEAM_ID de CTA."""
    import rival_analyzer

    if refresh:
        import spider
        click.echo(f"Actualizando datos del equipo {team_id}...")
        spider.crawl_single_team(team_id)

    report = rival_analyzer.format_rival_report(team_id)
    click.echo(report)


@cli.command()
@click.option("--rival", "rival_query", default=None, help="Nombre o substring del equipo rival")
@click.option("--rival-id", "rival_id", type=int, default=None, help="CTA ID del rival")
@click.option("--category", default=None, help="Filtrar por categoría (ej. '6M', '5F')")
@click.option("--gender", type=click.Choice(["M", "F"], case_sensitive=False), default=None, help="Género M/F")
@click.option("--last-n", type=int, default=10, show_default=True, help="Ventana de partidos a analizar")
@click.option("--json", "as_json", is_flag=True, help="Output JSON crudo")
def draw(rival_query, rival_id, category, gender, last_n, as_json):
    """Predecir draw contra un rival y sugerir alineacion."""
    import draw_predictor
    import json as _json

    # ── Resolver rival ──
    if rival_id is None and rival_query is None:
        click.echo("Error: especifica --rival NOMBRE o --rival-id CTA_ID")
        sys.exit(1)

    if rival_id is None:
        matches = database.search_teams(query=rival_query, category=category, gender=gender)
        matches = [t for t in matches if not t.get("is_own_team")]
        if not matches:
            click.echo(f"No se encontró ningún equipo con '{rival_query}'")
            sys.exit(1)
        if len(matches) > 1:
            click.echo(f"Se encontraron {len(matches)} equipos. Sé más específico o usa --rival-id:")
            for t in matches:
                cat = t.get("categoria_name") or ""
                gen = t.get("league_gender") or ""
                click.echo(f"  ID {t['cta_id']:>6}: {t['name']:<30} {cat} {gen}")
            sys.exit(1)
        rival_id = matches[0]["cta_id"]

    team = database.get_team(rival_id)
    if not team:
        click.echo(f"Error: no se encontró equipo con CTA ID {rival_id}")
        sys.exit(1)

    if not as_json:
        click.echo(f"[Draw] Analizando rival: {team['name']} (ID {rival_id})")

    # ── Generar reporte ──
    if as_json:
        data = draw_predictor.build_draw_report(rival_id, last_n=last_n)
        click.echo(_json.dumps(data, ensure_ascii=False, indent=2))
    else:
        report = draw_predictor.format_draw_report(rival_id, last_n=last_n)
        click.echo(report)


@cli.command()
@click.option("--all", "all_matches", is_flag=True, help="Backfill todos los partidos completados")
@click.option("--team", "team_cta_id", type=int, default=None, help="Solo partidos del equipo (CTA ID)")
@click.option("--force", is_flag=True, help="Re-scrape aunque ya haya rubbers en DB")
def rubbers(all_matches, team_cta_id, force):
    """Poblar match_rubbers scrapeando create_result de cada partido."""
    import spider

    if not all_matches and team_cta_id is None:
        click.echo("Error: especifica --all o --team CTA_ID")
        sys.exit(1)

    last_match_id = {"id": None}

    def progress(idx, total, match_id, status):
        if status == "ok" or status == "already_present":
            symbol = "·" if status == "already_present" else "+"
        elif status == "no_fixture":
            symbol = "?"
        else:
            symbol = "x"
        click.echo(f"  [{idx}/{total}] match={match_id} {symbol} {status}")
        last_match_id["id"] = match_id

    click.echo(f"[Rubbers] Backfill {'completo' if all_matches else f'team={team_cta_id}'} (force={force})")
    result = spider.backfill_all_match_rubbers(
        only_completed=True,
        team_cta_id=team_cta_id,
        force=force,
        progress_cb=progress,
    )

    click.echo(
        f"\n[Rubbers] Procesados:{result.get('processed', 0)} "
        f"Insertados:{result.get('scraped', 0)} "
        f"YaPresentes:{result.get('already_present', 0)} "
        f"Skip:{result.get('skipped', 0)} "
        f"SinFixture:{result.get('missing_fixture', 0)} "
        f"Errores:{result.get('errors', 0)}"
    )


@cli.command()
def report():
    """Generar reporte completo: tabla + proximo rival + prediccion."""
    import rival_analyzer
    import draw_predictor

    # Standings
    standings = database.get_latest_standings()
    if standings:
        click.echo(f"\n{'='*50}")
        click.echo("  TABLA DE POSICIONES")
        click.echo(f"{'='*50}")
        for s in standings:
            click.echo(
                f"  {s.get('position', '?'):>2}. {s['team_name']:<25} "
                f"PJ:{s.get('played', '?')} PG:{s.get('won', '?')} "
                f"PP:{s.get('lost', '?')} Pts:{s.get('points', '?')}"
            )
    else:
        click.echo("Sin datos de tabla. Ejecuta 'python main.py crawl' primero.")

    # Own team info
    own = database.get_own_team()
    if own:
        click.echo(f"\n{'='*50}")
        click.echo(f"  {own['name']} — Jugadores")
        click.echo(f"{'='*50}")
        players = database.get_team_players(own["cta_id"])
        for p in players:
            stats = database.get_latest_player_stats(p["cta_id"])
            rank = stats.get("ranking", "N/A") if stats else "N/A"
            click.echo(f"  {p['name']} (Ranking: {rank})")

    # All teams for reference
    teams = database.get_all_teams()
    if teams:
        click.echo(f"\n{'='*50}")
        click.echo("  TODOS LOS EQUIPOS")
        click.echo(f"{'='*50}")
        for t in teams:
            marker = " *" if t.get("is_own_team") else ""
            click.echo(f"  ID {t['cta_id']}: {t['name']}{marker}")


@cli.command()
def sync():
    """Sync rapido: crawl propio equipo + proximo rival."""
    import spider
    import auth

    session = auth.get_session()
    if not session:
        click.echo("Error: No se pudo autenticar.")
        sys.exit(1)

    # Always crawl standings first
    click.echo("[Sync] Actualizando tabla de posiciones...")
    spider.crawl_standings(session)

    # Crawl own team
    click.echo(f"[Sync] Actualizando equipo propio ({config.OWN_TEAM_ID})...")
    spider.crawl_single_team(config.OWN_TEAM_ID, session)

    # Crawl all groups for own category
    own_groups = config.GROUPS.get(config.CATEGORIA_ID, [])
    league = database.get_league(config.LIGA_ID, config.CATEGORIA_ID)
    league_id = league["id"] if league else None
    for grupo_num, group_id in own_groups:
        click.echo(f"[Sync] Actualizando grupo {group_id} (Grupo {grupo_num})...")
        spider.crawl_group(group_id, session, league_id=league_id, grupo_num=grupo_num)

    click.echo("[Sync] Completado.")


@cli.command()
def group():
    """Crawl todos los grupos de la liga (posiciones + fixture por grupo)."""
    import spider
    import auth

    session = auth.get_session()
    if not session:
        click.echo("Error: No se pudo autenticar.")
        sys.exit(1)

    total_standings = 0
    total_fixtures  = 0

    for cat in config.CATEGORIES:
        cat_id   = cat["id"]
        cat_name = cat["name"]
        groups   = config.GROUPS.get(cat_id, [])
        if not groups:
            continue

        # Obtener o crear la league en la BD
        league = database.get_league(config.LIGA_ID, cat_id)
        if not league:
            league_id = database.upsert_league(
                config.LIGA_ID, cat_id,
                name=cat_name, gender=cat.get("gender"),
                level=cat.get("level"), categoria_name=cat_name,
            )
        else:
            league_id = league["id"]

        for grupo_num, group_id in groups:
            click.echo(f"[Group] {cat_name} Grupo {grupo_num} (id={group_id})...")
            result = spider.crawl_group(group_id, session, league_id=league_id, grupo_num=grupo_num)
            total_standings += result.get("standings", 0)
            total_fixtures  += result.get("fixtures", 0)
            click.echo(f"         → {result.get('group_name','?')}: {result.get('standings',0)} pos / {result.get('fixtures',0)} fix")

    click.echo(f"\n[Group] Total posiciones: {total_standings}")
    click.echo(f"[Group] Total partidos:   {total_fixtures}")
    click.echo("[Group] Completado.")


if __name__ == "__main__":
    cli()
