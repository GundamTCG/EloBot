def update_elo(winner_elo, loser_elo, k=32):
  expected_win = 1 / (1 + 10 ** ((loser_elo - winner_elo) / 400))
  expected_loss = 1 - expected_win

  new_winner = round(winner_elo + k * (1 - expected_win))
  new_loser = round(loser_elo + k * (0 - expected_loss))
  return new_winner, new_loser
