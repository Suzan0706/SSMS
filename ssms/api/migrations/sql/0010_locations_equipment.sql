-- Regions and districts become reference tables; room equipment becomes searchable rows.
--
-- The list follows the 2022 census divisions as published by citypopulation.de (from the National Bureau of Statistics).
-- VERIFY against the current PO-RALG list before launch: councils are split and renamed from time to time. A new or
-- renamed district is added by a new migration, like other reference data.
SET ROLE ssms_owner;

CREATE TABLE regions (
    id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name  VARCHAR(40) NOT NULL UNIQUE
);
CREATE TABLE districts (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    region_id  UUID        NOT NULL REFERENCES regions (id),
    name       VARCHAR(40) NOT NULL,
    CONSTRAINT uq_districts UNIQUE (region_id, name)
);

WITH list (region, names) AS (VALUES
 ('Arusha', ARRAY['Arusha City','Arusha Rural','Karatu','Longido','Meru','Monduli','Ngorongoro']),
 ('Dar es Salaam', ARRAY['Dar es Salaam City','Kigamboni Municipal','Kinondoni Municipal','Temeke Municipal','Ubungo Municipal']),
 ('Dodoma', ARRAY['Bahi','Chamwino','Chemba','Dodoma City','Kondoa Rural','Kondoa Town','Kongwa','Mpwapwa']),
 ('Geita', ARRAY['Bukombe','Chato','Geita Rural','Geita Town','Mbogwe','Nyang''hwale']),
 ('Iringa', ARRAY['Iringa Municipal','Iringa Rural','Kilolo','Mafinga Town','Mufindi']),
 ('Kagera', ARRAY['Biharamulo','Bukoba Municipal','Bukoba Rural','Karagwe','Kyerwa','Missenyi','Muleba','Ngara']),
 ('Kaskazini Pemba', ARRAY['Micheweni','Wete']),
 ('Kaskazini Unguja', ARRAY['Kaskazini A','Kaskazini B']),
 ('Katavi', ARRAY['Mlele','Mpanda Municipal','Mpimbwe','Nsimbo','Tanganyika']),
 ('Kigoma', ARRAY['Buhigwe','Kakonko','Kasulu Rural','Kasulu Town','Kibondo','Kigoma Municipal','Kigoma Rural','Uvinza']),
 ('Kilimanjaro', ARRAY['Hai','Moshi Municipal','Moshi Rural','Mwanga','Rombo','Same','Siha']),
 ('Kusini Pemba', ARRAY['Chake Chake','Mkoani']),
 ('Kusini Unguja', ARRAY['Kati','Kusini']),
 ('Lindi', ARRAY['Kilwa','Lindi Municipal','Liwale','Mtama','Nachingwea','Ruangwa']),
 ('Manyara', ARRAY['Babati Rural','Babati Town','Hanang','Kiteto','Mbulu Rural','Mbulu Town','Simanjiro']),
 ('Mara', ARRAY['Bunda Rural','Bunda Town','Butiama','Musoma Municipal','Musoma Rural','Rorya','Serengeti','Tarime Rural','Tarime Town']),
 ('Mbeya', ARRAY['Busokelo','Chunya','Kyela','Mbarali','Mbeya City','Mbeya Rural','Rungwe']),
 ('Mjini Magharibi', ARRAY['Magharibi A Municipal','Magharibi B Municipal','Mjini Municipal']),
 ('Morogoro', ARRAY['Gairo','Ifakara Town','Kilosa','Malinyi','Mlimba','Morogoro Municipal','Morogoro Rural','Mvomero','Ulanga']),
 ('Mtwara', ARRAY['Masasi Rural','Masasi Town','Mtwara Municipal','Mtwara Rural','Nanyamba Town','Nanyumbu','Newala Rural','Newala Town','Tandahimba']),
 ('Mwanza', ARRAY['Buchosa','Ilemela Municipal','Kwimba','Magu','Misungwi','Mwanza City','Sengerema','Ukerewe']),
 ('Njombe', ARRAY['Ludewa','Makambako Town','Makete','Njombe Rural','Njombe Town','Wanging''ombe']),
 ('Pwani', ARRAY['Bagamoyo','Chalinze','Kibaha','Kibaha Town','Kibiti','Kisarawe','Mafia','Mkuranga','Rufiji']),
 ('Rukwa', ARRAY['Kalambo','Nkasi','Sumbawanga Municipal','Sumbawanga Rural']),
 ('Ruvuma', ARRAY['Madaba','Mbinga Rural','Mbinga Town','Namtumbo','Nyasa','Songea Municipal','Songea Rural','Tunduru']),
 ('Shinyanga', ARRAY['Kahama Municipal','Kishapu','Msalala','Shinyanga Municipal','Shinyanga Rural','Ushetu']),
 ('Simiyu', ARRAY['Bariadi Rural','Bariadi Town','Busega','Itilima','Maswa','Meatu']),
 ('Singida', ARRAY['Ikungi','Iramba','Itigi','Manyoni','Mkalama','Singida Municipal','Singida Rural']),
 ('Songwe', ARRAY['Ileje','Mbozi','Momba','Songwe','Tunduma Town']),
 ('Tabora', ARRAY['Igunga','Kaliua','Nzega Rural','Nzega Town','Sikonge','Tabora Municipal','Urambo','Uyui']),
 ('Tanga', ARRAY['Bumbuli','Handeni Rural','Handeni Town','Kilindi','Korogwe Rural','Korogwe Town','Lushoto','Mkinga','Muheza','Pangani','Tanga City'])
), new_regions AS (
    INSERT INTO regions (name) SELECT region FROM list RETURNING id, name
)
INSERT INTO districts (region_id, name)
SELECT r.id, d.name FROM new_regions r JOIN list l ON l.region = r.name CROSS JOIN LATERAL unnest(l.names) AS d(name);

ALTER TABLE schools ADD COLUMN district_id UUID REFERENCES districts (id);

CREATE TABLE equipment_items (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id   UUID        NOT NULL REFERENCES schools (id),
    name        VARCHAR(60) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by  UUID,
    deleted_at  TIMESTAMPTZ,
    CONSTRAINT uq_equipment_items_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_ei_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id)
);
CREATE UNIQUE INDEX uq_equipment_items_name ON equipment_items (school_id, lower(name)) WHERE deleted_at IS NULL;

CREATE TABLE room_equipment (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    school_id     UUID        NOT NULL REFERENCES schools (id),
    room_id       UUID        NOT NULL,
    equipment_id  UUID        NOT NULL,
    quantity      SMALLINT    NOT NULL DEFAULT 1,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by    UUID,
    deleted_at    TIMESTAMPTZ,
    CONSTRAINT uq_room_equipment_tenant UNIQUE (school_id, id),
    CONSTRAINT fk_re_room FOREIGN KEY (school_id, room_id) REFERENCES rooms (school_id, id),
    CONSTRAINT fk_re_item FOREIGN KEY (school_id, equipment_id) REFERENCES equipment_items (school_id, id),
    CONSTRAINT fk_re_created_by FOREIGN KEY (school_id, created_by) REFERENCES users (school_id, id),
    CONSTRAINT ck_re_quantity CHECK (quantity > 0)
);
CREATE UNIQUE INDEX uq_room_equipment ON room_equipment (school_id, room_id, equipment_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_room_equipment_item ON room_equipment (school_id, equipment_id) WHERE deleted_at IS NULL;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['equipment_items','room_equipment'] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (school_id = app_school_id()) '
                       'WITH CHECK (school_id = app_school_id())', t);
        EXECUTE format('CREATE TRIGGER trg_%s_updated BEFORE UPDATE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_touch_updated_at()', t, t);
        EXECUTE format('CREATE TRIGGER trg_%s_audit AFTER INSERT OR UPDATE OR DELETE ON %I '
                       'FOR EACH ROW EXECUTE FUNCTION fn_audit_row()', t, t);
    END LOOP;
END $$;

RESET ROLE;
GRANT SELECT ON regions, districts TO ssms_app, ssms_platform, ssms_reporting;
GRANT SELECT, INSERT, UPDATE ON equipment_items, room_equipment TO ssms_app, ssms_platform;
GRANT SELECT ON equipment_items, room_equipment TO ssms_reporting;

-- Data, as the migration login (RLS would hide every row from the owner role).
-- A school whose text matches no district stops the migration: better to fix it by hand than to guess.
UPDATE schools s SET district_id = d.id
FROM districts d JOIN regions r ON r.id = d.region_id
WHERE lower(trim(s.region)) = lower(r.name) AND lower(trim(s.district)) = lower(d.name);

DO $$
DECLARE missing text;
BEGIN
    SELECT string_agg(format('%s (%s / %s)', code, region, district), ', ') INTO missing
    FROM schools WHERE district_id IS NULL;
    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'No matching district for: %. Correct these schools, then run the migration again.', missing;
    END IF;
END $$;

-- '45 desks, whiteboard' becomes rows: Desks x 45, Whiteboard x 1.
CREATE TEMP TABLE parsed_equipment ON COMMIT DROP AS
SELECT school_id, room_id, upper(left(item, 1)) || substr(item, 2) AS name, MAX(quantity) AS quantity
FROM (
    SELECT r.school_id, r.id AS room_id,
           left(trim(regexp_replace(trim(part), '^\d{1,4}\s+', '')), 60) AS item,
           COALESCE((regexp_match(trim(part), '^(\d{1,4})\s'))[1]::smallint, 1) AS quantity
    FROM rooms r CROSS JOIN LATERAL regexp_split_to_table(r.equipment, ',') AS part
    WHERE r.equipment IS NOT NULL AND trim(part) <> ''
) p
WHERE quantity > 0
GROUP BY school_id, room_id, upper(left(item, 1)) || substr(item, 2);

INSERT INTO equipment_items (school_id, name)
SELECT school_id, MIN(name) FROM parsed_equipment GROUP BY school_id, lower(name);

INSERT INTO room_equipment (school_id, room_id, equipment_id, quantity)
SELECT p.school_id, p.room_id, e.id, MAX(p.quantity)
FROM parsed_equipment p
JOIN equipment_items e ON e.school_id = p.school_id AND lower(e.name) = lower(p.name)
GROUP BY p.school_id, p.room_id, e.id;

SET ROLE ssms_owner;
ALTER TABLE schools ALTER COLUMN district_id SET NOT NULL;
ALTER TABLE schools DROP COLUMN region, DROP COLUMN district;
ALTER TABLE rooms DROP COLUMN equipment;
RESET ROLE;
