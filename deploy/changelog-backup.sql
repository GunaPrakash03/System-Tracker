--
-- PostgreSQL database dump
--

\restrict aTpdI3joH4NT0U1edfV9DtdBRGL5XdpwpZ8G1MaQyEK0aogQIduxS2EzvWWKsya

-- Dumped from database version 17.10
-- Dumped by pg_dump version 17.10

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: changelog; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.changelog (id, "createdAt", "updatedAt", "tenantId", "organizationId", icon, title, date, content, "learnMoreUrl", "isFeature", "imageUrl", "isActive", "isArchived", "deletedAt", "archivedAt", "createdByUserId", "updatedByUserId", "deletedByUserId") FROM stdin;
2ed62f6c-5aa7-4c32-bcc7-7764b0d25392	2026-08-05 06:19:47.565278	2026-08-05 06:19:47.565278	\N	\N	cube-outline	See new features	2026-08-05 06:19:35.292	Now you can read latest features changelog directly in Gauzy		f		t	f	\N	\N	\N	\N	\N
78e7094d-260c-4641-a193-c39d318c57e8	2026-08-05 06:19:47.565278	2026-08-05 06:19:47.565278	\N	\N	globe-outline	Ready to give Gauzy a try?	2026-08-05 06:19:35.292	Customer relationship management, enterprise resource planning, sales management, supply chain management and production management		f		t	f	\N	\N	\N	\N	\N
865beae2-f19a-4cb0-aae7-bc57f9c2092d	2026-08-05 06:19:47.565278	2026-08-05 06:19:47.565278	\N	\N	flash-outline	Visit our website for more information.	2026-08-05 06:19:35.292	You are welcome to check more information about the platform at our official website.	https://gauzy.co/	f		t	f	\N	\N	\N	\N	\N
ef70621c-72bf-407d-9a4d-442104454fad	2026-08-05 06:19:47.565278	2026-08-05 06:19:47.565278	\N	\N	cube-outline	New CRM	2026-08-05 06:19:35.292	Now you can read latest features changelog directly in Gauzy		t	assets/images/features/macbook-2.png	t	f	\N	\N	\N	\N	\N
4739ba7a-b40b-49fb-b63b-9e2d56431a4b	2026-08-05 06:19:47.565278	2026-08-05 06:19:47.565278	\N	\N	globe-outline	Most popular in 20 countries	2026-08-05 06:19:35.292	Europe, Americas and Asia get choice		t	assets/images/features/macbook-1.png	t	f	\N	\N	\N	\N	\N
5db80846-a0d2-46fe-b5dd-6d600d7f4379	2026-08-05 06:19:47.565278	2026-08-05 06:19:47.565278	\N	\N	flash-outline	Visit our website	2026-08-05 06:19:35.292	You are welcome to check more information about the platform at our official website.		t		t	f	\N	\N	\N	\N	\N
\.


--
-- PostgreSQL database dump complete
--

\unrestrict aTpdI3joH4NT0U1edfV9DtdBRGL5XdpwpZ8G1MaQyEK0aogQIduxS2EzvWWKsya

