// Runs only when a brand-new Mongo data volume is initialized.
const database = db.getSiblingDB(process.env.MONGO_INITDB_DATABASE || "telepilot");
database.createUser({
    user: "telepilot",
    pwd: process.env.MONGO_APP_PASSWORD,
    roles: [{role: "readWrite", db: process.env.MONGO_INITDB_DATABASE || "telepilot"}]
});
