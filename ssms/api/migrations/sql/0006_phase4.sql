-- Phase 4 (Attendance and communication). Runs as the migration role; objects stay owned by ssms_owner.
SET ROLE ssms_owner;

-- SMS delivery reports arrive from the provider with only its message id: find the message (and its school) the
-- same way GePG callbacks are routed. Partial index: most rows have an id once sent.
CREATE INDEX ix_sms_messages_provider_id ON sms_messages (provider, provider_message_id)
    WHERE provider_message_id IS NOT NULL;

CREATE FUNCTION resolve_sms_message(p_provider TEXT, p_provider_message_id TEXT)
RETURNS TABLE (school_id UUID, sms_id UUID)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
    SELECT m.school_id, m.id FROM public.sms_messages m
    WHERE m.provider = p_provider AND m.provider_message_id = p_provider_message_id
$$;

-- Who registered a device or issued a card, and what an announcement said, is audited (hashes are redacted).
CREATE TRIGGER trg_devices_audit AFTER INSERT OR UPDATE OR DELETE ON devices
    FOR EACH ROW EXECUTE FUNCTION fn_audit_row();
CREATE TRIGGER trg_rfid_cards_audit AFTER INSERT OR UPDATE OR DELETE ON rfid_cards
    FOR EACH ROW EXECUTE FUNCTION fn_audit_row();
CREATE TRIGGER trg_announcements_audit AFTER INSERT OR UPDATE OR DELETE ON announcements
    FOR EACH ROW EXECUTE FUNCTION fn_audit_row();
CREATE TRIGGER trg_message_templates_audit AFTER INSERT OR UPDATE OR DELETE ON message_templates
    FOR EACH ROW EXECUTE FUNCTION fn_audit_row();

RESET ROLE;

ALTER FUNCTION resolve_sms_message(TEXT, TEXT) OWNER TO ssms_resolver;
GRANT SELECT (school_id, id, provider, provider_message_id) ON sms_messages TO ssms_resolver;
REVOKE ALL ON FUNCTION resolve_sms_message(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION resolve_sms_message(TEXT, TEXT) TO ssms_app;

-- SMS credit is a ledger too: rows are only added (TOPUP, DEBIT, REFUND), never changed.
REVOKE UPDATE ON sms_credit_transactions FROM ssms_app, ssms_platform;
