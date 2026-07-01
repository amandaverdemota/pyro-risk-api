import pandas as pd

df = pd.read_csv("feux_et_fwi.csv")

# Filtrer les incendies avec fwi_class "low" ou "very_low"
df_filtre = df[df["fwi_class"].isin(["low", "very_low"])].copy()

# Nombre d'incendies restants
print(f"Nombre d'incendies (low + very_low) : {len(df_filtre)}")