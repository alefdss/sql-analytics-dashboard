CREATE TABLE public.users (
    user_id bigint PRIMARY KEY DEFAULT nextval('users_id_seq'),
    created_at timestamp DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE public.questions (
    question_id integer PRIMARY KEY DEFAULT nextval('questions_id_seq'),
    question text NOT NULL,
    type text NOT NULL,
    options text
);

CREATE TABLE public.responses (
    id bigint PRIMARY KEY DEFAULT nextval('responses_id_seq'),
    user_id bigint REFERENCES public.users(user_id),
    question_id integer REFERENCES public.questions(question_id),
    answer text,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    survey_id uuid
);
