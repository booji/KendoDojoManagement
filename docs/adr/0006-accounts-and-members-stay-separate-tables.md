# Accounts and Members stay separate tables

A **Member** is the kendoka: name, email, date of birth, grade, emergency
contact, safeguarding data. An **Account** is how a Member signs in: passkeys,
recovery codes, **Role** (the code called it `User` / `users` until #436). Every
Account belongs to exactly one Member — there is no sign-in without a kendoka,
the first **Admin** included, whose Member is created when they claim the
instance. Most Members have no Account. The obvious simplification is one
`people` table; we keep two, linked by a NOT NULL, unique `accounts.member_id`,
for three reasons.

- **They are deleted differently.** Erasure hard-deletes the Account and its
  credentials but anonymises the Member in place, so attendance keeps a row
  to point at. A single table would need a tombstone row with every auth
  column nulled: two tables sharing one row. (Grade history is deleted on
  erasure, not kept: a grade and the date it was awarded can single out a
  kendoka even under "Deleted member", so keeping it would not be erasure —
  #447.)
- **They are read under different trust conditions.** Accounts are looked up
  by the unauthenticated registration and login endpoints, where enumeration
  and timing parity have had real work (#239, #267, #300). Members hold the
  personal and under-18 data. Merging them puts that data on the row that
  pre-auth lookups load.
- **The roster outlives sign-ins.** Most Members never sign in, and a Member
  who leaves loses their Account but keeps their history.

The email address is stored once, on the Member, and is both the contact
address and the sign-in identifier: two copies that must always be equal is
one copy. Pre-auth code therefore finds an Account by joining its Member on
that one indexed column — it matches on `members.email` and loads only the
Account, never the Member row, so the trust boundary above still holds. Only
an Admin can change the address; the app sends no mail, so a self-service
change could not be verified.

Decided in the schema review, issue #418.
