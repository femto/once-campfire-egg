`schema.sql` is the schema `bin/rails db:prepare` gives a fresh database:
once-campfire-rust's crates/db/src/schema.sql (MIT), the `sqlite_master` of
a database the Rails app created, without what SQLite makes on its own.
script/schema.rb turns it into src/schema.egg.
