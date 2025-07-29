import aiosqlite

async def initialize():
    async with aiosqlite.connect("/data/db.sqlite") as db:
        await db.execute("""
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY,
            wins_1v1 INTEGER DEFAULT 0,
            losses_1v1 INTEGER DEFAULT 0,
            elo_1v1 INTEGER DEFAULT 1000,
            wins_2v2 INTEGER DEFAULT 0,
            losses_2v2 INTEGER DEFAULT 0,
            elo_2v2 INTEGER DEFAULT 1000
        )
        """)
        await db.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id INTEGER PRIMARY KEY,
            mode TEXT NOT NULL,
            host_id INTEGER NOT NULL,
            players TEXT NOT NULL,
            teams TEXT,
            status TEXT NOT NULL,
            message_id INTEGER,
            channel_id INTEGER
        )
        """)

        await db.commit()

async def ensure_player_exists(player_id: int):
    async with aiosqlite.connect("/data/db.sqlite") as db:
        await db.execute(
            "INSERT OR IGNORE INTO players (id) VALUES (?)", (player_id,)
        )
        await db.commit()

async def get_player(player_id: int, mode: str):
    await ensure_player_exists(player_id)
    async with aiosqlite.connect("/data/db.sqlite") as db:
        cursor = await db.execute(
            f"SELECT wins_{mode}, losses_{mode}, elo_{mode} FROM players WHERE id = ?",
            (player_id,)
        )
        result = await cursor.fetchone()
        return result or (0, 0, 1000)

async def update_stats(winner_id: int, loser_id: int, mode: str):
    await ensure_player_exists(winner_id)
    await ensure_player_exists(loser_id)

    async with aiosqlite.connect("/data/db.sqlite") as db:
        # Get current ELO
        winner_cursor = await db.execute(
            f"SELECT elo_{mode} FROM players WHERE id = ?", (winner_id,)
        )
        winner_stats = await winner_cursor.fetchone()

        loser_cursor = await db.execute(
            f"SELECT elo_{mode} FROM players WHERE id = ?", (loser_id,)
        )
        loser_stats = await loser_cursor.fetchone()

        winner_elo = winner_stats[0]
        loser_elo = loser_stats[0]

        # Simple ELO calculation
        k = 32
        expected_win = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
        new_winner_elo = round(winner_elo + k * (1 - expected_win))
        new_loser_elo = round(loser_elo - k * expected_win)

        # Update stats
        await db.execute(
            f"""
            UPDATE players SET
                wins_{mode} = wins_{mode} + 1,
                elo_{mode} = ?
            WHERE id = ?
            """, (new_winner_elo, winner_id)
        )

        await db.execute(
            f"""
            UPDATE players SET
                losses_{mode} = losses_{mode} + 1,
                elo_{mode} = ?
            WHERE id = ?
            """, (new_loser_elo, loser_id)
        )

        await db.commit()

import json

async def save_match(match_id, mode, host_id, players, teams, status, message_id=None):
    players_json = json.dumps(players)
    teams_json = json.dumps(teams) if teams else None
    async with aiosqlite.connect("/data/db.sqlite") as db:
        await db.execute("""
            INSERT OR REPLACE INTO matches (match_id, mode, host_id, players, teams, status, message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (match_id, mode, host_id, players_json, teams_json, status, message_id,channel_id))
        await db.commit()


async def remove_match(match_id):
    async with aiosqlite.connect("/data/db.sqlite") as db:
        await db.execute("DELETE FROM matches WHERE match_id=?", (match_id,))
        await db.commit()

async def get_active_matches():
    async with aiosqlite.connect("/data/db.sqlite") as db:
        cursor = await db.execute("SELECT match_id, mode, host_id, players, teams, status, message_id, channel_id FROM matches WHERE status = 'active'")
        rows = await cursor.fetchall()
        matches = []
        for row in rows:
            match = {
                "match_id": row[0],
                "mode": row[1],
                "host_id": row[2],
                "players": json.loads(row[3]),
                "teams": json.loads(row[4]) if row[4] else None,
                "status": row[5],
                "message_id": row[6],
                "channel_id": row[7]
            }
            matches.append(match)
        return matches

