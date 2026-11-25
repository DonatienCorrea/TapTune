# Configurer le Wi-Fi de TapTune

[Accueil en français](./) · [Checklist d’installation en anglais](../raspberry-pi-service.md)

## Première installation

Dans Raspberry Pi Imager, choisissez Raspberry Pi OS Lite ou Desktop. Avant
d’écrire la carte, personnalisez le système : définissez un nom d’hôte (par
exemple `taptune`), le nom et le mot de passe du Wi-Fi ainsi que le pays du
réseau sans fil. Créez votre compte et activez SSH si vous installez TapTune à
distance. Au démarrage, connectez votre ordinateur au même réseau et accédez au
Pi via `taptune.local` (ou le nom choisi). Le point d’accès de secours n’est
disponible qu’une fois le service TapTune installé.

## Changer de réseau Wi-Fi depuis un téléphone

Sous Raspberry Pi OS Lite et Desktop avec NetworkManager, si le Pi ne trouve
pas de connexion Wi-Fi connue ni de liaison Ethernet après environ une minute
au démarrage, il diffuse le réseau `TapTune-Setup`.

Le point d’accès reste protégé par WPA2 avec un mot de passe unique au Pi.
Lors de la première configuration, TapTune affiche un QR Wi-Fi et le mot de
passe lorsqu’il crée le profil. Scannez le code dans les réglages Wi-Fi du
téléphone pour le connecter : le mot de passe est transmis au téléphone, mais
le point d’accès reste protégé. Gardez le QR et le mot de passe privés : toute
personne qui rejoint le réseau peut configurer le Pi.

```bash
taptune setup-wifi
```

Exécutez cette commande avant de déplacer le Pi pour réafficher le QR et le
mot de passe. `taptune reset` les affiche aussi avant d’effacer les réseaux
Wi-Fi enregistrés.

1. Démarrez le Pi au nouvel emplacement. Scannez le QR dans les réglages Wi-Fi
   du téléphone ou choisissez `TapTune-Setup` et saisissez le mot de passe
   imprimé. Restez connecté même si le téléphone indique que le réseau n’a pas
   accès à Internet.
2. Si la page de connexion ne s’ouvre pas, ouvrez `http://10.42.66.1/fr/setup`
   dans le navigateur (utilisez `http://`, sans `s`). Sélectionnez un réseau
   détecté avant le démarrage du point d’accès, ou saisissez son nom, puis
   renseignez son **mot de passe Wi-Fi**. Laissez le champ vide uniquement
   pour un réseau ouvert. Les réseaux d’entreprise et ceux qui exigent une
   connexion dans le navigateur ne sont pas pris en charge.
3. Le point d’accès disparaît pendant la tentative. Reconnectez votre
   téléphone au réseau choisi et ouvrez `http://taptune.local/fr/` (adaptez
   le nom d’hôte). Si le port 80 est indisponible, essayez
   `http://taptune.local:5000/fr/` (ou le port `APP_PORT` configuré).
   Si le Pi n’a pas pu se connecter,
   `TapTune-Setup` réapparaît : rejoignez-le et réessayez.

Le formulaire Wi-Fi n’est accessible que depuis le point d’accès. Celui-ci ne
donne pas accès à Internet ni à l’interface habituelle de TapTune. NetworkManager
enregistre les identifiants Wi-Fi, pas TapTune. Une réinstallation conserve le
mot de passe du point d’accès. Pour désactiver le secours Wi-Fi, ajoutez
`TAPTUNE_WIFI_SETUP=false` au fichier `.env` et redémarrez TapTune.
