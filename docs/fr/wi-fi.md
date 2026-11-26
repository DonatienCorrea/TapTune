# Configurer le Wi-Fi de TapTune

[Accueil en français](./) · [Guide d’installation (anglais)](../raspberry-pi-service.md)

## Première installation

Suivez le [guide d’installation](../raspberry-pi-service.md#1-prepare-the-sd-card)
pour configurer le premier Wi-Fi dans Raspberry Pi Imager.

## Changer de réseau Wi-Fi depuis un téléphone

Si le Pi ne trouve aucun réseau connu environ une minute après le démarrage, il
crée son propre Wi-Fi **TapTune-Setup** (protégé par un mot de passe propre à ce Pi).

1. Avant de déplacer le Pi, exécutez `taptune setup-wifi` si vous n’avez pas
   gardé le mot de passe affiché à l’installation. Un QR code s’affiche aussi
   si `qrencode` est installé.
2. Au nouvel endroit, scannez le QR code s’il est disponible ou rejoignez
   `TapTune-Setup` avec le mot de passe. Restez connecté même si le téléphone
   indique « pas d’Internet ».
3. La page de configuration s’ouvre. Sinon, allez sur `http://10.42.66.1/fr/setup`
   (`http://`, sans `s`).
4. Choisissez votre Wi-Fi et saisissez son mot de passe. Le Pi quitte
   `TapTune-Setup` et s’y connecte.
5. Reconnectez le téléphone à votre Wi-Fi et ouvrez `http://taptune.local/fr/`
   (ou `http://taptune.local:5000/fr/`). En cas d’échec, `TapTune-Setup`
   réapparaît : réessayez.

Le mot de passe Wi-Fi ne peut être saisi que depuis `TapTune-Setup`. Les réseaux
d’entreprise et ceux qui demandent une connexion dans le navigateur ne sont pas
pris en charge. Gardez le QR code privé : quiconque rejoint ce réseau peut
configurer le Pi. Pour désactiver ce secours, ajoutez `TAPTUNE_WIFI_SETUP=false`
dans `.env` puis exécutez `./install.sh --configure` depuis le dossier TapTune.

## Maintenance sans écran

La page **Journal** (`http://taptune.local/fr/logs`) affiche l’activité et
permet de mettre à jour TapTune, de le redémarrer, de redémarrer le Pi et de
télécharger les journaux de diagnostic.
