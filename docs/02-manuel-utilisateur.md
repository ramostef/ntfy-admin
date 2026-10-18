# RMS — Manuel utilisateur

## Se connecter

Ouvrez [http://localhost:5173](http://localhost:5173) sur le réseau local, ou l’adresse HTTPS publique communiquée pour RMS. Saisissez le mot de passe RMS. La page d’accueil présente l’état des missions, profils et notifications.

## Créer une mission et contacter des profils

1. Dans **Accueil**, choisissez **Créer une mission**.
2. Renseignez les informations utiles : poste, client, lieu, secteur, dates et nombre de postes, puis enregistrez.
3. Ouvrez la mission et choisissez **Voir les profils correspondants**. Cette liste sert à consulter les profils proposés.
4. Cochez les profils à contacter. Vérifiez qu’ils disposent d’un canal ntfy actif.
5. Choisissez **Notifier les profils sélectionnés**. RMS envoie une notification ntfy aux profils cochés. Le résultat s’affiche dans la fenêtre et l’activité récente.

La sélection permet de choisir les profils individuellement ; elle n’envoie pas automatiquement une notification à toute la liste.

## Gérer les profils intérimaires

Ouvrez **Profils** dans la navigation.

- Recherchez par nom ou prénom et filtrez par secteur d’activité.
- Utilisez **Ajouter un intérimaire** pour créer une fiche.
- Ouvrez une fiche pour modifier les informations, le secteur, les périodes de disponibilité et le canal ntfy.
- Pour libérer un canal, utilisez l’action de retrait du canal ntfy. Un canal affecté à un autre profil peut apparaître indisponible.

Les coordonnées de canal doivent correspondre à un topic et à un compte ntfy opérationnels. Faites un essai de notification après une nouvelle affectation.

## Préparer et envoyer un contrat

1. Ouvrez **Contrats & signature**, puis **Nouveau brouillon**.
2. Sélectionnez la mission et l’intérimaire, saisissez son adresse e-mail et le nom et l’adresse e-mail du signataire de l’agence.
3. Joignez le contrat PDF non signé (maximum 10 Mo), puis choisissez **Enregistrer le brouillon**.
4. Dans **Contrats préparés**, vérifiez le contrat et les deux adresses affichées.
5. Choisissez **Envoyer aux 2 signataires**. Les invitations sont envoyées par e-mail et le contrat passe à l’état **Envoyé**.

Le bouton d’envoi est affiché pour les brouillons et les envois en échec. Il disparaît après un envoi réussi pour éviter le renvoi involontaire. Les destinataires doivent aussi vérifier leurs courriers indésirables.

## Modules et formules

La zone **Votre espace, à la carte** et la page **Modules** présentent les modules disponibles dans la maquette. Les options visibles dépendent de la configuration actuelle de RMS.

## À savoir sur la signature

Le parcours actuel est un prototype : RMS envoie un lien individuel à l’intérimaire et à l’agence, puis conserve le nom saisi, le consentement et l’horodatage. Il ne s’agit pas d’une signature électronique qualifiée. Vérifiez le statut des deux réponses dans le module Contrats & signature.
