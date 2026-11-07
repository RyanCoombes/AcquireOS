-- "Treat as one business" was removed: show any companies combined with it again.
update user_company set merged_into = null where merged_into is not null;
