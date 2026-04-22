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
@click.argument("rival_id", type=int)
def draw(rival_id):
    """Predecir draw contra un rival y sugerir alineacion."""
    import draw_predictor

    report = draw_predictor.format_draw_report(rival_id)
    click.echo(report)


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

    # Crawl group page (standings + fixtures for our group)
    click.echo(f"[Sync] Actualizando grupo {config.GROUP_ID}...")
    spider.crawl_group(config.GROUP_ID, session)

    click.echo("[Sync] Completado.")


@cli.command()
def group():
    """Crawl solo la pagina del grupo (posiciones + fixture)."""
    import spider
    import auth

    session = auth.get_session()
    if not session:
        click.echo("Error: No se pudo autenticar.")
        sys.exit(1)

    click.echo(f"[Group] Scrapeando grupo {config.GROUP_ID}...")
    result = spider.crawl_group(config.GROUP_ID, session)
    click.echo(f"[Group] Posiciones guardadas: {result.get('standings', 0)}")
    click.echo(f"[Group] Partidos guardados:   {result.get('fixtures', 0)}")
    click.echo("[Group] Completado.")


if __name__ == "__main__":
    cli()
