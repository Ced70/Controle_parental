#!/usr/bin/env bash
# Lance le contrôle parental complet : AdGuard Home (DNS) + backend Rust.
# Le backend doit être lancé depuis le dossier projet (il lit pages/,
# config.json, questions.json et la base SQLite relativement au répertoire courant).
cd "$(dirname "$0")/.." || exit 1

# 1) AdGuard Home (filtrage DNS). Son redémarrage auto est désactivé :
#    c'est ce script qui le démarre.
if [ "$(docker inspect -f '{{.State.Running}}' adguardhome 2>/dev/null)" != "true" ]; then
    echo "Démarrage d'AdGuard Home (DNS)..."
    docker start adguardhome || { echo "ÉCHEC du démarrage d'AdGuard !"; read -r -p "Entrée pour fermer..."; exit 1; }
else
    echo "AdGuard Home tourne déjà."
fi

# Après un reboot du DGX, le conteneur revient parfois détaché du réseau Docker
# (Networks = {}, port 53 non publié → DNS mort). On le détecte et on répare.
if [ "$(docker inspect -f '{{len .NetworkSettings.Networks}}' adguardhome)" = "0" ]; then
    echo "AdGuard est détaché du réseau Docker → rattachement au bridge..."
    docker network connect bridge adguardhome
    docker restart adguardhome
    sleep 3
fi

# Vérification finale : le DNS répond-il vraiment ?
if dig +short +time=3 +tries=1 @192.168.1.51 google.com >/dev/null 2>&1; then
    echo "DNS AdGuard OK (192.168.1.51:53)."
else
    echo "⚠️  ATTENTION : le DNS 192.168.1.51:53 ne répond pas ! (voir « docker logs adguardhome »)"
fi

# 2) Backend Rust. Déjà lancé ? On ne démarre pas un doublon.
if curl -s -m 2 http://localhost:8090/health >/dev/null; then
    echo "Le serveur tourne déjà (http://192.168.1.51:8090)."
    echo "Pour l'arrêter : pkill -x controle_parent"
    read -r -p "Entrée pour fermer..."
    exit 0
fi

echo "Démarrage du serveur de contrôle parental sur :8090 ..."
echo "(Ctrl+C pour l'arrêter — laisser cette fenêtre ouverte.)"
echo "(AdGuard, lui, reste actif après fermeture : « docker stop adguardhome » pour le couper.)"
exec ./target/release/controle_parental
