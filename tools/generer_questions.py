#!/usr/bin/env python3
"""Génère la banque de questions à choix multiples (5 choix) du contrôle parental.
Sortie : ../questions.json (niveaux : simple / moyen / difficile).

Composition par niveau = ~900 questions de MATHS (calculées, réponses exactes)
+ TOUTES les questions de SUJETS curés (culture, sciences, français, anglais),
dont les distracteurs sont tirés de la même catégorie (donc plausibles).
Réexécutable : `python3 generer_questions.py`.
"""
import json
import os
import random
from collections import Counter

random.seed(2024)
MATH_CIBLE = 900  # nb de questions de maths conservées par niveau


# ============================ Helpers ============================
def distracteurs_num(correct, n=4):
    cands, step = [], max(1, abs(correct) // 10)
    base = [1, -1, 2, -2, 3, -3, 5, -5, 10, -10, 11, -11, 20, -20, step, -step, 2 * step, -2 * step]
    random.shuffle(base)
    for d in base:
        v = correct + d
        if v != correct and v >= 0 and v not in cands:
            cands.append(v)
        if len(cands) >= n:
            break
    k = 1
    while len(cands) < n:
        for v in (correct + k * 7, correct - k * 7, correct + k * 13):
            if v != correct and v >= 0 and v not in cands:
                cands.append(v)
            if len(cands) >= n:
                break
        k += 1
    return cands[:n]


def qn(niveau, enonce, correct):
    opts = [str(x) for x in distracteurs_num(correct)] + [str(correct)]
    random.shuffle(opts)
    return {"niveau": niveau, "enonce": enonce, "choix": opts, "bonne": opts.index(str(correct))}


def qt(niveau, enonce, correct, pool):
    autres = [x for x in dict.fromkeys(pool) if x != correct]
    if len(autres) < 4:
        return None
    random.shuffle(autres)
    opts = autres[:4] + [correct]
    random.shuffle(opts)
    return {"niveau": niveau, "enonce": enonce, "choix": opts, "bonne": opts.index(correct)}


# ---- Nombres en lettres (règles françaises traditionnelles, 0-100) ----
_UNITES = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
           "onze", "douze", "treize", "quatorze", "quinze", "seize", "dix-sept", "dix-huit", "dix-neuf"]
_DIZAINES = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante", 60: "soixante", 80: "quatre-vingt"}


def en_lettres(n):
    if n < 20:
        return _UNITES[n]
    if n == 100:
        return "cent"
    if n < 70:                      # 20-69
        t, u = (n // 10) * 10, n % 10
        if u == 0:
            return _DIZAINES[t]
        if u == 1:
            return _DIZAINES[t] + " et un"
        return _DIZAINES[t] + "-" + _UNITES[u]
    if n < 80:                      # 70-79
        return "soixante et onze" if n == 71 else "soixante-" + _UNITES[n - 60]
    if n == 80:                     # 80-99
        return "quatre-vingts"
    return "quatre-vingt-" + _UNITES[n - 80]


MOTS_NOMBRES = [en_lettres(k) for k in range(0, 101)]
NOMBRES_NIVEAU = {"simple": list(range(11, 40)), "moyen": list(range(40, 70)), "difficile": list(range(70, 100))}


# ============================ Données curées ============================
CAPITALES = {
    "simple": {"France": "Paris", "Espagne": "Madrid", "Italie": "Rome", "Allemagne": "Berlin",
               "Belgique": "Bruxelles", "Suisse": "Berne", "Portugal": "Lisbonne", "Royaume-Uni": "Londres",
               "Pays-Bas": "Amsterdam", "Autriche": "Vienne", "Irlande": "Dublin", "Grèce": "Athènes",
               "Luxembourg": "Luxembourg", "Monaco": "Monaco", "Danemark": "Copenhague"},
    "moyen": {"États-Unis": "Washington", "Canada": "Ottawa", "Japon": "Tokyo", "Chine": "Pékin",
              "Russie": "Moscou", "Brésil": "Brasilia", "Mexique": "Mexico", "Australie": "Canberra",
              "Égypte": "Le Caire", "Maroc": "Rabat", "Suède": "Stockholm", "Norvège": "Oslo",
              "Pologne": "Varsovie", "Turquie": "Ankara", "Inde": "New Delhi", "Argentine": "Buenos Aires",
              "Finlande": "Helsinki", "Islande": "Reykjavik", "Hongrie": "Budapest", "République tchèque": "Prague",
              "Roumanie": "Bucarest", "Croatie": "Zagreb", "Ukraine": "Kiev", "Cuba": "La Havane", "Thaïlande": "Bangkok"},
    "difficile": {"Chili": "Santiago", "Pérou": "Lima", "Colombie": "Bogota", "Venezuela": "Caracas",
                  "Uruguay": "Montevideo", "Équateur": "Quito", "Corée du Sud": "Séoul", "Vietnam": "Hanoï",
                  "Indonésie": "Jakarta", "Philippines": "Manille", "Pakistan": "Islamabad", "Iran": "Téhéran",
                  "Irak": "Bagdad", "Arabie saoudite": "Riyad", "Liban": "Beyrouth", "Syrie": "Damas",
                  "Sénégal": "Dakar", "Afrique du Sud": "Pretoria", "Kenya": "Nairobi", "Nigéria": "Abuja",
                  "Éthiopie": "Addis-Abeba", "Ghana": "Accra", "Cameroun": "Yaoundé", "Mali": "Bamako",
                  "Madagascar": "Antananarivo", "Serbie": "Belgrade", "Bulgarie": "Sofia", "Slovaquie": "Bratislava",
                  "Slovénie": "Ljubljana", "Nouvelle-Zélande": "Wellington"},
}
TOUTES_CAPITALES = [c for d in CAPITALES.values() for c in d.values()]
TOUS_PAYS = [p for d in CAPITALES.values() for p in d.keys()]

ANGLAIS = {
    "simple": {"un": "one", "deux": "two", "trois": "three", "quatre": "four", "cinq": "five", "six": "six",
               "sept": "seven", "huit": "eight", "neuf": "nine", "dix": "ten", "rouge": "red", "bleu": "blue",
               "vert": "green", "jaune": "yellow", "noir": "black", "blanc": "white", "rose": "pink", "marron": "brown",
               "chien": "dog", "chat": "cat", "cheval": "horse", "vache": "cow", "oiseau": "bird", "poisson": "fish",
               "mère": "mother", "père": "father", "frère": "brother", "sœur": "sister", "garçon": "boy", "fille": "girl",
               "maison": "house", "école": "school", "eau": "water", "soleil": "sun", "lune": "moon", "livre": "book",
               "voiture": "car", "arbre": "tree", "grand": "big", "petit": "small", "oui": "yes", "non": "no",
               "bonjour": "hello", "manger": "eat", "boire": "drink", "jouer": "play", "courir": "run", "chaud": "hot", "froid": "cold"},
    "moyen": {"lundi": "Monday", "mardi": "Tuesday", "mercredi": "Wednesday", "jeudi": "Thursday", "vendredi": "Friday",
              "samedi": "Saturday", "dimanche": "Sunday", "pomme": "apple", "pain": "bread", "lait": "milk",
              "fromage": "cheese", "œuf": "egg", "viande": "meat", "gâteau": "cake", "riz": "rice", "poulet": "chicken",
              "ours": "bear", "loup": "wolf", "renard": "fox", "lapin": "rabbit", "singe": "monkey", "éléphant": "elephant",
              "tête": "head", "main": "hand", "pied": "foot", "bras": "arm", "jambe": "leg", "bouche": "mouth",
              "heureux": "happy", "triste": "sad", "rapide": "fast", "lent": "slow", "fort": "strong", "beau": "beautiful",
              "lire": "read", "écrire": "write", "parler": "speak", "voir": "see", "dormir": "sleep", "chanter": "sing",
              "fleur": "flower", "ciel": "sky", "mer": "sea", "étoile": "star", "pluie": "rain", "neige": "snow"},
    "difficile": {"janvier": "January", "février": "February", "mars": "March", "avril": "April", "mai": "May",
                  "juin": "June", "juillet": "July", "août": "August", "septembre": "September", "octobre": "October",
                  "novembre": "November", "décembre": "December", "vingt": "twenty", "trente": "thirty", "cent": "hundred",
                  "mille": "thousand", "serpent": "snake", "papillon": "butterfly", "araignée": "spider", "tortue": "turtle",
                  "grenouille": "frog", "abeille": "bee", "dauphin": "dolphin", "baleine": "whale", "professeur": "teacher",
                  "médecin": "doctor", "agriculteur": "farmer", "hôpital": "hospital", "marché": "market", "gare": "station",
                  "montagne": "mountain", "rivière": "river", "forêt": "forest", "ville": "city", "difficile": "difficult",
                  "facile": "easy", "cher": "expensive", "propre": "clean", "sale": "dirty", "hier": "yesterday",
                  "aujourd'hui": "today", "demain": "tomorrow", "matin": "morning", "soir": "evening", "argent": "money",
                  "ami": "friend", "travail": "work", "langue": "language", "histoire": "story"},
}
ANGLAIS_PLUS = {
    "simple": {"chapeau": "hat", "robe": "dress", "chaussure": "shoe", "sac": "bag", "clé": "key", "lit": "bed",
               "table": "table", "chaise": "chair", "porte": "door", "fenêtre": "window", "jouet": "toy",
               "balle": "ball", "banane": "banana", "fraise": "strawberry", "nez": "nose", "oreille": "ear",
               "œil": "eye", "cheveux": "hair", "doigt": "finger", "dent": "tooth", "ouvrir": "open",
               "fermer": "close", "donner": "give", "marcher": "walk", "sauter": "jump"},
    "moyen": {"tomate": "tomato", "carotte": "carrot", "soupe": "soup", "sucre": "sugar", "sel": "salt",
              "beurre": "butter", "jus": "juice", "café": "coffee", "thé": "tea", "chocolat": "chocolate",
              "canard": "duck", "poule": "hen", "cochon": "pig", "mouton": "sheep", "souris": "mouse", "chèvre": "goat",
              "acheter": "buy", "aider": "help", "attendre": "wait", "trouver": "find", "penser": "think",
              "jardin": "garden", "plage": "beach", "lac": "lake", "pont": "bridge", "route": "road", "jeune": "young",
              "lourd": "heavy", "léger": "light", "vide": "empty"},
    "difficile": {"quarante": "forty", "cinquante": "fifty", "soixante": "sixty", "pays": "country", "monde": "world",
                  "guerre": "war", "paix": "peace", "roi": "king", "reine": "queen", "président": "president",
                  "pompier": "firefighter", "avocat": "lawyer", "ingénieur": "engineer", "désert": "desert",
                  "océan": "ocean", "vague": "wave", "tempête": "storm", "tonnerre": "thunder", "dangereux": "dangerous",
                  "calme": "quiet", "intelligent": "smart", "courageux": "brave", "célèbre": "famous", "voyager": "travel",
                  "apprendre": "learn", "enseigner": "teach", "construire": "build", "gagner": "win", "perdre": "lose", "semaine": "week"},
}
for _niv in ANGLAIS:
    ANGLAIS[_niv].update(ANGLAIS_PLUS[_niv])
TOUS_EN = [m for d in ANGLAIS.values() for m in d.values()]
TOUS_FR = [m for d in ANGLAIS.values() for m in d.keys()]

PLANETES = ["Mercure", "Vénus", "Terre", "Mars", "Jupiter", "Saturne", "Uranus", "Neptune"]
SYMBOLES = ["Au", "Ag", "Fe", "O", "H", "C", "Na", "Ca", "K", "N", "Cl", "Cu", "Zn", "Al", "Hg", "Pb", "S", "Mg", "He"]
ORGANES = ["le cœur", "le foie", "les poumons", "l'estomac", "les reins", "le cerveau", "la peau"]
SCIENCES = [
    ("simple", "Combien de pattes a une araignée ?", "8", None),
    ("simple", "Combien de pattes a un insecte ?", "6", None),
    ("simple", "À combien de degrés l'eau bout-elle ?", "100", None),
    ("simple", "À combien de degrés l'eau gèle-t-elle ?", "0", None),
    ("simple", "Combien de couleurs dans un arc-en-ciel ?", "7", None),
    ("simple", "Combien de jours dans une semaine ?", "7", None),
    ("simple", "Combien de mois dans une année ?", "12", None),
    ("simple", "Combien d'heures dans une journée ?", "24", None),
    ("simple", "Sur quelle planète vivons-nous ?", "Terre", PLANETES),
    ("simple", "Quel astre tourne autour de la Terre ?", "la Lune", ["la Lune", "le Soleil", "Mars", "Vénus", "une comète"]),
    ("moyen", "Quelle est la planète la plus proche du Soleil ?", "Mercure", PLANETES),
    ("moyen", "Quelle est la plus grande planète du système solaire ?", "Jupiter", PLANETES),
    ("moyen", "Quelle est la planète rouge ?", "Mars", PLANETES),
    ("moyen", "Quel gaz respirons-nous pour vivre ?", "l'oxygène", ["l'oxygène", "l'azote", "le dioxyde de carbone", "l'hélium", "l'hydrogène"]),
    ("moyen", "Quel organe pompe le sang ?", "le cœur", ORGANES),
    ("moyen", "Quel organe permet de respirer ?", "les poumons", ORGANES),
    ("moyen", "Quel est le symbole chimique de l'or ?", "Au", SYMBOLES),
    ("moyen", "Quel est le symbole chimique du fer ?", "Fe", SYMBOLES),
    ("moyen", "Quel est le symbole chimique de l'oxygène ?", "O", SYMBOLES),
    ("moyen", "Quel est l'état de l'eau à -10 °C ?", "solide", ["solide", "liquide", "gazeux", "plasma", "vapeur"]),
    ("difficile", "Quel est le symbole chimique de l'argent ?", "Ag", SYMBOLES),
    ("difficile", "Quel est le symbole chimique du sodium ?", "Na", SYMBOLES),
    ("difficile", "Quel est le symbole chimique du carbone ?", "C", SYMBOLES),
    ("difficile", "Quel est le symbole chimique du potassium ?", "K", SYMBOLES),
    ("difficile", "Quel est le symbole chimique du cuivre ?", "Cu", SYMBOLES),
    ("difficile", "Combien d'os compte le corps humain adulte ?", "206", None),
    ("difficile", "Combien de dents a un adulte (avec les dents de sagesse) ?", "32", None),
    ("difficile", "Quel organe filtre le sang (par paire) ?", "les reins", ORGANES),
    ("difficile", "Combien de planètes dans le système solaire ?", "8", None),
    ("difficile", "Quel gaz les plantes produisent-elles le jour ?", "l'oxygène", ["l'oxygène", "l'azote", "le méthane", "l'hélium", "le dioxyde de carbone"]),
]

PLURIELS = {"cheval": "chevaux", "journal": "journaux", "animal": "animaux", "hibou": "hiboux", "genou": "genoux",
            "château": "châteaux", "bateau": "bateaux", "oiseau": "oiseaux", "jeu": "jeux", "travail": "travaux",
            "œil": "yeux", "caillou": "cailloux", "chou": "choux", "bijou": "bijoux", "pou": "poux",
            "ciel": "cieux", "monsieur": "messieurs", "madame": "mesdames", "corail": "coraux", "vitrail": "vitraux"}
TOUS_PLURIELS = list(PLURIELS.values())
ANTONYMES = {"grand": "petit", "chaud": "froid", "jour": "nuit", "content": "triste", "rapide": "lent",
             "monter": "descendre", "ouvrir": "fermer", "gentil": "méchant", "haut": "bas", "plein": "vide",
             "propre": "sale", "riche": "pauvre", "clair": "sombre", "dur": "mou", "fort": "faible",
             "large": "étroit", "lourd": "léger", "sec": "mouillé", "vrai": "faux", "premier": "dernier",
             "sucré": "salé", "jeune": "vieux", "facile": "difficile", "gagner": "perdre"}
TOUS_ANTONYMES = list(ANTONYMES.values())
CONJ_PRESENT = {
    "être": {"je": "je suis", "tu": "tu es", "il": "il est", "nous": "nous sommes", "vous": "vous êtes", "ils": "ils sont"},
    "avoir": {"je": "j'ai", "tu": "tu as", "il": "il a", "nous": "nous avons", "vous": "vous avez", "ils": "ils ont"},
    "aller": {"je": "je vais", "tu": "tu vas", "il": "il va", "nous": "nous allons", "vous": "vous allez", "ils": "ils vont"},
    "faire": {"je": "je fais", "tu": "tu fais", "il": "il fait", "nous": "nous faisons", "vous": "vous faites", "ils": "ils font"},
    "pouvoir": {"je": "je peux", "tu": "tu peux", "il": "il peut", "nous": "nous pouvons", "vous": "vous pouvez", "ils": "ils peuvent"},
    "vouloir": {"je": "je veux", "tu": "tu veux", "il": "il veut", "nous": "nous voulons", "vous": "vous voulez", "ils": "ils veulent"},
    "venir": {"je": "je viens", "tu": "tu viens", "il": "il vient", "nous": "nous venons", "vous": "vous venez", "ils": "ils viennent"},
    "prendre": {"je": "je prends", "tu": "tu prends", "il": "il prend", "nous": "nous prenons", "vous": "vous prenez", "ils": "ils prennent"},
    "dire": {"je": "je dis", "tu": "tu dis", "il": "il dit", "nous": "nous disons", "vous": "vous dites", "ils": "ils disent"},
    "voir": {"je": "je vois", "tu": "tu vois", "il": "il voit", "nous": "nous voyons", "vous": "vous voyez", "ils": "ils voient"},
    "savoir": {"je": "je sais", "tu": "tu sais", "il": "il sait", "nous": "nous savons", "vous": "vous savez", "ils": "ils savent"},
    "finir": {"je": "je finis", "tu": "tu finis", "il": "il finit", "nous": "nous finissons", "vous": "vous finissez", "ils": "ils finissent"},
}
CONJ_IMPARFAIT = {
    "être": {"je": "j'étais", "tu": "tu étais", "il": "il était", "nous": "nous étions", "vous": "vous étiez", "ils": "ils étaient"},
    "avoir": {"je": "j'avais", "tu": "tu avais", "il": "il avait", "nous": "nous avions", "vous": "vous aviez", "ils": "ils avaient"},
    "faire": {"je": "je faisais", "tu": "tu faisais", "il": "il faisait", "nous": "nous faisions", "vous": "vous faisiez", "ils": "ils faisaient"},
    "aller": {"je": "j'allais", "tu": "tu allais", "il": "il allait", "nous": "nous allions", "vous": "vous alliez", "ils": "ils allaient"},
}
TOUTES_FORMES = ([f for v in CONJ_PRESENT.values() for f in v.values()]
                 + [f for v in CONJ_IMPARFAIT.values() for f in v.values()])

VERBES_PAR_NIVEAU = {"simple": ["être", "avoir", "aller", "faire"],
                     "moyen": ["pouvoir", "vouloir", "venir", "prendre"],
                     "difficile": ["dire", "voir", "savoir", "finir"]}

# Féminins (masculin -> féminin), par niveau de difficulté.
FEMININS = {
    "simple": {"chat": "chatte", "chien": "chienne", "lion": "lionne", "roi": "reine", "prince": "princesse",
               "garçon": "fille", "homme": "femme", "père": "mère", "frère": "sœur", "beau": "belle"},
    "moyen": {"acteur": "actrice", "chanteur": "chanteuse", "boulanger": "boulangère", "vendeur": "vendeuse",
              "danseur": "danseuse", "oncle": "tante", "neveu": "nièce", "nouveau": "nouvelle", "vieux": "vieille",
              "heureux": "heureuse", "gentil": "gentille", "blanc": "blanche"},
    "difficile": {"instituteur": "institutrice", "directeur": "directrice", "infirmier": "infirmière",
                  "héros": "héroïne", "époux": "épouse", "cheval": "jument", "taureau": "vache", "mouton": "brebis",
                  "fou": "folle", "roux": "rousse", "frais": "fraîche", "doux": "douce", "long": "longue", "sportif": "sportive"},
}
TOUS_FEMININS = [f for d in FEMININS.values() for f in d.values()]
TOUS_MASCULINS = [m for d in FEMININS.values() for m in d.keys()]

# Continents (pays -> continent) ; on évite les pays transcontinentaux ambigus.
CONTINENTS_LISTE = ["Europe", "Asie", "Afrique", "Amérique", "Océanie"]
CONTINENTS = {
    "États-Unis": "Amérique", "Canada": "Amérique", "Japon": "Asie", "Chine": "Asie", "Brésil": "Amérique",
    "Mexique": "Amérique", "Australie": "Océanie", "Égypte": "Afrique", "Maroc": "Afrique", "Suède": "Europe",
    "Norvège": "Europe", "Pologne": "Europe", "Inde": "Asie", "Argentine": "Amérique", "Finlande": "Europe",
    "Islande": "Europe", "Hongrie": "Europe", "République tchèque": "Europe", "Roumanie": "Europe", "Croatie": "Europe",
    "Ukraine": "Europe", "Cuba": "Amérique", "Thaïlande": "Asie", "Chili": "Amérique", "Pérou": "Amérique",
    "Colombie": "Amérique", "Venezuela": "Amérique", "Uruguay": "Amérique", "Équateur": "Amérique",
    "Corée du Sud": "Asie", "Vietnam": "Asie", "Indonésie": "Asie", "Philippines": "Asie", "Pakistan": "Asie",
    "Iran": "Asie", "Irak": "Asie", "Arabie saoudite": "Asie", "Liban": "Asie", "Syrie": "Asie", "Sénégal": "Afrique",
    "Afrique du Sud": "Afrique", "Kenya": "Afrique", "Nigéria": "Afrique", "Éthiopie": "Afrique", "Ghana": "Afrique",
    "Cameroun": "Afrique", "Mali": "Afrique", "Madagascar": "Afrique", "Serbie": "Europe", "Bulgarie": "Europe",
    "Slovaquie": "Europe", "Slovénie": "Europe", "Nouvelle-Zélande": "Océanie",
}


# ============================ Questions « sujets » ============================
def sujets(niveau):
    out = []
    for pays, cap in CAPITALES[niveau].items():
        out.append(qt(niveau, f"Quelle est la capitale de : {pays} ?", cap, TOUTES_CAPITALES))
        out.append(qt(niveau, f"De quel pays {cap} est-elle la capitale ?", pays, TOUS_PAYS))
    for fr, en in ANGLAIS[niveau].items():
        out.append(qt(niveau, f"Comment dit-on « {fr} » en anglais ?", en, TOUS_EN))
        out.append(qt(niveau, f"Que veut dire « {en} » en français ?", fr, TOUS_FR))
    for niv, enonce, correct, pool in SCIENCES:
        if niv == niveau:
            out.append(qn(niveau, enonce, int(correct)) if pool is None else qt(niveau, enonce, correct, pool))
    # Pluriels : simple + moyen
    if niveau in ("simple", "moyen"):
        items = list(PLURIELS.items())
        for mot, plur in (items[:10] if niveau == "simple" else items[10:]):
            out.append(qt(niveau, f"Quel est le pluriel de « {mot} » ?", plur, TOUS_PLURIELS))
    # Antonymes : répartis sur les 3 niveaux
    items = list(ANTONYMES.items())
    tranche = {"simple": items[:8], "moyen": items[8:16], "difficile": items[16:]}[niveau]
    for mot, ant in tranche:
        out.append(qt(niveau, f"Quel est le contraire de « {mot} » ?", ant, TOUS_ANTONYMES))
    # Conjugaison présent (verbes selon le niveau)
    for verbe in VERBES_PAR_NIVEAU[niveau]:
        for pron, forme in CONJ_PRESENT[verbe].items():
            out.append(qt(niveau, f"Conjugue « {verbe} » avec « {pron} » au présent.", forme, TOUTES_FORMES))
    # Imparfait : seulement au niveau difficile
    if niveau == "difficile":
        for verbe, formes in CONJ_IMPARFAIT.items():
            for pron, forme in formes.items():
                out.append(qt(niveau, f"Conjugue « {verbe} » avec « {pron} » à l'imparfait.", forme, TOUTES_FORMES))
    # Féminins (deux sens)
    for masc, fem in FEMININS[niveau].items():
        out.append(qt(niveau, f"Quel est le féminin de « {masc} » ?", fem, TOUS_FEMININS))
        out.append(qt(niveau, f"Quel est le masculin de « {fem} » ?", masc, TOUS_MASCULINS))
    # Continents (niveaux moyen et difficile, où les pays varient vraiment)
    if niveau in ("moyen", "difficile"):
        for pays in CAPITALES[niveau]:
            if pays in CONTINENTS:
                out.append(qt(niveau, f"Sur quel continent se trouve : {pays} ?", CONTINENTS[pays], CONTINENTS_LISTE))
    # Nombres en lettres (deux sens)
    for n in random.sample(NOMBRES_NIVEAU[niveau], 18):
        out.append(qt(niveau, f"Comment écrit-on {n} en lettres ?", en_lettres(n), MOTS_NOMBRES))
        out.append(qn(niveau, f"Que vaut « {en_lettres(n)} » en chiffres ?", n))
    return [x for x in out if x]


# ============================ Maths (volume conservé) ============================
def math_simple():
    t = random.choice(["mult", "add", "sub", "double", "triple"])
    if t == "mult":
        a, b = random.randint(2, 12), random.randint(2, 12); return qn("simple", f"Combien font {a} × {b} ?", a * b)
    if t == "add":
        a, b = random.randint(11, 99), random.randint(11, 99); return qn("simple", f"Combien font {a} + {b} ?", a + b)
    if t == "sub":
        a = random.randint(30, 99); b = random.randint(10, a); return qn("simple", f"Combien font {a} − {b} ?", a - b)
    if t == "double":
        a = random.randint(11, 99); return qn("simple", f"Quel est le double de {a} ?", 2 * a)
    a = random.randint(3, 33); return qn("simple", f"Quel est le triple de {a} ?", 3 * a)


def math_moyen():
    t = random.choice(["mult", "div", "pct", "step", "square", "half"])
    if t == "mult":
        a, b = random.randint(11, 99), random.randint(3, 9); return qn("moyen", f"Combien font {a} × {b} ?", a * b)
    if t == "div":
        b, r = random.randint(3, 12), random.randint(3, 12); return qn("moyen", f"Combien font {b * r} ÷ {b} ?", r)
    if t == "pct":
        p, base = random.choice([10, 25, 50, 75]), random.choice([20, 40, 60, 80, 100, 120, 160, 200]); return qn("moyen", f"Combien font {p} % de {base} ?", p * base // 100)
    if t == "step":
        a, b, c = random.randint(2, 12), random.randint(2, 12), random.randint(2, 5); return qn("moyen", f"Combien font ({a} + {b}) × {c} ?", (a + b) * c)
    if t == "square":
        a = random.randint(5, 15); return qn("moyen", f"Combien font {a}² ?", a * a)
    a = random.randint(10, 49) * 2; return qn("moyen", f"Quelle est la moitié de {a} ?", a // 2)


def math_difficile():
    t = random.choice(["mult", "sqrt", "pct", "step", "power", "conv", "sumsq"])
    if t == "mult":
        a, b = random.randint(11, 40), random.randint(11, 30); return qn("difficile", f"Combien font {a} × {b} ?", a * b)
    if t == "sqrt":
        a = random.randint(4, 25); return qn("difficile", f"Quelle est la racine carrée de {a * a} ?", a)
    if t == "pct":
        p, base = random.choice([5, 15, 20, 30, 35, 40, 60, 80]), random.choice([120, 160, 200, 240, 300, 400, 80])
        v = p * base / 100
        return qn("difficile", f"Combien font {p} % de {base} ?", int(v)) if v == int(v) else math_difficile()
    if t == "step":
        a, b, c, d = random.randint(3, 12), random.randint(2, 9), random.randint(2, 9), random.randint(1, 20); return qn("difficile", f"Combien font ({a} + {b}) × {c} − {d} ?", (a + b) * c - d)
    if t == "power":
        base, n = random.choice([2, 3]), random.randint(2, 6 if random.random() < 0.5 else 4); return qn("difficile", f"Combien font {base}^{n} ?", base ** n)
    if t == "conv":
        h = random.randint(1, 4); return qn("difficile", f"Combien de secondes dans {h} h ?", h * 3600)
    a, b = random.randint(3, 12), random.randint(3, 12); return qn("difficile", f"Combien font {a}² + {b}² ?", a * a + b * b)


# ============================ Assemblage ============================
def construire(niveau, gen_math):
    vus, out = set(), []
    for item in sujets(niveau):                 # tous les sujets curés
        if item["enonce"] not in vus:
            vus.add(item["enonce"]); out.append(item)
    n_sujets = len(out)
    essais = 0
    while len(out) - n_sujets < MATH_CIBLE and essais < 80000:  # + maths conservées
        essais += 1
        item = gen_math()
        if item and item["enonce"] not in vus:
            vus.add(item["enonce"]); out.append(item)
    random.shuffle(out)
    return out, n_sujets


banque, stats = [], {}
for niveau, gen in [("simple", math_simple), ("moyen", math_moyen), ("difficile", math_difficile)]:
    qs, n_sujets = construire(niveau, gen)
    banque += qs
    stats[niveau] = {"total": len(qs), "sujets": n_sujets, "maths": len(qs) - n_sujets}

for it in banque:
    assert len(it["choix"]) == 5 and len(set(it["choix"])) == 5, it
    assert 0 <= it["bonne"] < 5

dest = os.path.join(os.path.dirname(__file__), "..", "questions.json")
with open(dest, "w", encoding="utf-8") as f:
    json.dump({"questions": banque}, f, ensure_ascii=False, indent=1)
print("questions.json généré — total", len(banque))
for niv, s in stats.items():
    print(f"  {niv}: {s['total']} (sujets {s['sujets']}, maths {s['maths']})")
