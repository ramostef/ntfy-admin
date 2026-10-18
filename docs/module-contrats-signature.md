# Module RMS : contrats et signature électronique

## Objectif

Développer dans RMS un module autonome, activable selon la formule du client, pour préparer un contrat de mission, demander sa signature, suivre chaque signataire et archiver le contrat avec les éléments de preuve.

RMS peut posséder son parcours, son interface, ses données et son historique. Une intégration avec un prestataire de confiance qualifié reste une option pour les contrats exigeant ce niveau ; elle n'est pas nécessaire pour démarrer un prototype interne.

## Parcours cible

1. Depuis une mission et les profils sélectionnés, l'utilisateur choisit **Préparer un contrat**.
2. RMS génère un document à partir d'un modèle versionné. L'utilisateur vérifie le projet avant envoi.
3. Le ou les signataires reçoivent un lien personnel et un code de vérification par e-mail.
4. Le signataire ouvre le contrat, confirme son identité selon le niveau retenu, accepte explicitement le contenu et confirme la signature.
5. RMS verrouille la version signée, enregistre les événements et met à disposition le contrat final et le dossier de preuve.

Le contrat en attente peut être joint au courriel pour lecture. Le parcours de signature s'ouvre sur le lien RMS. Le courriel n'est pas lui-même la signature.

## Signature interne : périmètre initial à valider

Une première version peut enregistrer un acte de signature RMS comprenant :

- l'identifiant du signataire et son e-mail vérifié ;
- le texte d'acceptation et la confirmation explicite ;
- l'empreinte cryptographique du document exact ;
- les horodatages et les événements du parcours ;
- une preuve de livraison du lien/code et une copie durable pour chaque partie.

Cela ne transforme pas RMS en prestataire qualifié eIDAS et ne permet pas d'annoncer une signature qualifiée. Le Code civil exige un procédé fiable d'identification qui lie la signature à l'acte ; l'adéquation du parcours RMS pour le type de contrat doit donc être validée par la personne RH/juridique responsable. Un prestataire qualifié pourra être ajouté plus tard comme adaptateur, si nécessaire.

## Activation par formule

La base SQLite contient déjà `client_formulas`, `formula_modules` et `client_formula_assignments`. L'identifiant du module proposé est `contracts_signature`.

L'accès devra être contrôlé côté backend selon le compte client et sa formule ; masquer le bouton dans le navigateur ne protège pas les routes. Le backend actuel utilise toutefois une session administrateur unique. Il faudra établir des sessions client et leur contexte avant une activation réelle par formule.

## Premier jalon implémenté

Le module administrateur RMS permet maintenant de créer un brouillon en choisissant une mission, un intérimaire, l'e-mail de l'intérimaire, le nom et l'e-mail du signataire de l'agence, puis en important un PDF non signé (10 Mo maximum). Le PDF est stocké dans `backend/data/contracts`, hors du dossier public, avec un nom aléatoire et une empreinte SHA-256. La liste RMS affiche les brouillons, les deux signataires et un téléchargement protégé par la session administrateur.

Ce jalon ne transmet pas de mail et ne recueille pas de signature. Il ne doit pas être présenté comme un contrat signé.

## État technique et étapes suivantes

- Les tables de formules existent, mais aucune route de gestion des formules/modules ni contrôle d'accès client n'est encore relié à la session administrateur unique.
- Les e-mails des signataires sont demandés sur chaque brouillon ; ils ne sont pas encore enregistrés dans les profils.
- Le fichier backend `.env` ne contient pas de paramètres d'envoi e-mail. RMS ne peut donc pas encore envoyer de lien ou de code de signature.
- Étape suivante : configurer un service d'envoi e-mail, puis créer des liens temporaires et le parcours de signature pour l'intérimaire et l'agence.
- Après validation du parcours, ajouter les vérifications d'identité, le journal de preuve, la conservation de la version signée et le contrôle d'activation par formule côté backend.

## Découpage de réalisation

### Étape 1 — modèle fonctionnel

- Décider les rôles signataires et l'ordre de signature.
- Ajouter les coordonnées e-mail nécessaires avec contrôle de format et possibilité de correction.
- Créer les contrats en état brouillon, leurs statuts et l'historique d'événements.
- Créer un aperçu vérifiable du contrat avant envoi.

### Étape 2 — envoi et signature contrôlée

- Configurer le serveur d'envoi via des variables serveur (jamais dans le navigateur ni le dépôt Git).
- Créer des liens signés, temporaires, à usage limité et protégés contre les essais répétés.
- Vérifier l'e-mail par code séparé, recueillir l'accord explicite et verrouiller la version du document.
- Générer et conserver une preuve d'audit ainsi qu'une copie téléchargeable.

### Étape 3 — formules et déploiement

- Relier les sessions client à leur `client_account_id`.
- Ajouter l'administration des formules et des modules, puis vérifier `contracts_signature` sur chaque route concernée.
- Valider avec le responsable RH/juridique le type de contrat et le niveau d'identification attendus.
- Ajouter une intégration QTSP uniquement si le besoin de signature qualifiée ou un niveau supérieur de vérification l'exige.

## Modèle de données indicatif

Un contrat conservera le client propriétaire, la mission et le profil liés, la version du modèle, la version/empreinte du document, le statut (`draft`, `sent`, `viewed`, `signed`, `declined`, `expired`, `failed`), les destinataires, les dates et l'historique. Les codes ne seront stockés qu'empreints et les jetons de signature sous forme hachée. Les documents signés ne seront jamais placés dans le dossier public du frontend.

## Décisions encore nécessaires

- Qui signe le premier type de contrat, et dans quel ordre ?
- Quel contrat et modèle validés démarrer en premier ?
- Quel est le niveau d'identification attendu par le responsable RH/juridique ?
- Quelle boîte ou quel service SMTP RMS utilisera-t-il pour envoyer les liens et codes ?
