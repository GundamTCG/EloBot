import aiosqlite

async def initialize():
    async with aiosqlite.connect("db.sqlite") as db:
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
        await db.commit()

async def ensure_player_exists(player_id: int):
    async with aiosqlite.connect("db.sqlite") as db:
        await db.execute(
            "INSERT OR IGNORE INTO players (id) VALUES (?)", (player_id,)
        )
        await db.commit()

async def get_player(player_id: int, mode: str):
    await ensure_player_exists(player_id)
    async with aiosqlite.connect("db.sqlite") as db:
        cursor = await db.execute(
            f"SELECT wins_{mode}, losses_{mode}, elo_{mode} FROM players WHERE id = ?",
            (player_id,)
        )
        result = await cursor.fetchone()
        return result or (0, 0, 1000)

async def update_stats(winner_id: int, loser_id: int, mode: str):
    await ensure_player_exists(winner_id)
    await ensure_player_exists(loser_id)

    async with aiosqlite.connect("db.sqlite") as db:
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
