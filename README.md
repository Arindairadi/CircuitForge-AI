
# CircuitForge AI

**An AI-assisted Electronic Design Automation (EDA) platform for designing, simulating, verifying, and exporting electronic circuits.**

CircuitForge AI combines artificial intelligence with traditional circuit design tools to simplify the electronic design process. It provides a platform for circuit creation, simulation, engineering verification, and PCB design workflows.

The project aims to make electronic design more accessible to students, engineers, researchers, and electronics enthusiasts.

## Features

### AI-Assisted Circuit Design
- Generate circuit designs using natural language prompts.
- Create and modify supported circuit configurations.
- Review proposed AI-generated changes before applying them.
- Provide intelligent assistance during circuit development.

### Circuit Simulation
- Run SPICE-based circuit simulations using ngspice.
- Perform operating-point analysis.
- Perform transient analysis.
- Perform AC analysis.
- Perform DC sweep analysis.
- Support parameter sweeps for supported circuits.

### Circuit Verification
- Perform basic electrical engineering checks.
- Validate supported component ratings.
- Identify potential circuit design issues.
- Assist with reviewing circuit configurations.

### KiCad Integration
- Export circuit schematics.
- Generate PDF schematic documents.
- Support PCB-related workflows.
- Export Gerber and drill files where supported.
- Support component placement exports.

### Additional Features
- Bill of Materials (BOM) generation.
- Component library management.
- Project versioning and comparison.
- Project sharing and collaboration.
- Design review tools.
- Circuit calculators.
- Basic PCB optimization.
- Approximate 3D PCB visualization.

## Technology Stack

| Component | Technology |
|---|---|
| Frontend | React, TypeScript, Vite |
| Backend | Python, FastAPI |
| Database | SQLAlchemy, Alembic |
| Simulation Engine | ngspice |
| PCB Design | KiCad |
| 3D Visualization | Three.js |
| Testing | pytest, Vitest |
| Development Environment | VS Code, Python, Node.js |

## Project Structure

```text
circuitforge-ai/
├── backend/
│   ├── app/
│   ├── tests/
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   ├── public/
│   └── package.json
│
├── docs/
│   └── limitations.md
│
├── scripts/
├── .github/
├── .env.example
├── docker-compose.yml
└── README.md
```

## Installation and Setup

### Prerequisites

Before running CircuitForge AI, ensure you have installed:

- Python 3.11 or later
- Node.js and npm
- Git
- ngspice
- KiCad (for supported PCB and schematic operations)

### 1. Clone the Repository

```bash
git clone https://github.com/Arindairadi/CircuitForge-AI.git
cd CircuitForge-AI
```


### 2. Set Up the Backend

Navigate to the backend directory:

```bash
cd backend
```

Create a Python virtual environment:

```bash
python -m venv .venv
```

Activate the virtual environment.

**Windows:**

```powershell
.venv\Scripts\Activate.ps1
```

**Linux / macOS:**

```bash
source .venv/bin/activate
```

Install the required dependencies:

```bash
pip install -r requirements.txt
```

Apply database migrations:

```bash
alembic upgrade head
```

Start the FastAPI server:

```bash
PYTHONPATH=. uvicorn app.main:app --reload
```

The backend will be available at:

```text
http://localhost:8000
```

API documentation:

```text
http://localhost:8000/docs
```

### 3. Set Up the Frontend

Open another terminal and navigate to the frontend directory:

```bash
cd frontend
```

Install the dependencies:

```bash
npm install
```

Start the development server:

```bash
npm run dev
```

Open the application in your browser:

```text
http://localhost:5173
```

## Environment Configuration

CircuitForge AI supports environment-based configuration.

Create a `.env` file using `.env.example` as a template.

Example configuration:

```env
DATABASE_URL=sqlite:///./circuitforge.db

CORS_ORIGINS=http://localhost:5173

AI_BASE_URL=
AI_API_KEY=
AI_MODEL=

MOUSER_API_KEY=

PCBNEW_PYTHON=

ARTIFACT_DIR=
```

Some features require external API credentials.

**Important:** Never commit your `.env` file, API keys, passwords, or other sensitive credentials to GitHub.

## Running Tests

### Backend Tests

From the backend directory:

```bash
PYTHONPATH=. python -m pytest -q
```

### Frontend Tests

From the frontend directory:

```bash
npm test
```

### Frontend Production Build

```bash
npm run build
```

### Integration Tests

From the project root:

```bash
./scripts/integration.sh
```

## Docker Deployment

A Docker Compose configuration is included in the project.

To build and start the services:

```bash
docker compose up --build
```

Docker deployment should be validated in your target environment before production use.

## Known Limitations

CircuitForge AI is currently an early-stage project.

Some limitations include:

- PCB layout functionality is limited to supported workflows.
- The 3D PCB preview is approximate.
- Some component models may not accurately represent real-world components.
- Verification tools support a limited set of circuit types and conditions.
- AI-generated designs require engineering review.
- External AI and supplier integrations require valid credentials.
- KiCad-related functionality depends on the installed KiCad environment.

For detailed information, see:

`docs/limitations.md`

## Future Improvements

Potential future improvements include:

- More advanced AI circuit generation.
- Improved PCB autorouting.
- Enhanced electrical rule checking.
- More accurate 3D PCB visualization.
- Expanded component libraries.
- Improved circuit optimization.
- More advanced simulation capabilities.
- Better collaboration tools.
- Additional AI-powered engineering assistance.

## Contributing

Contributions are welcome!

To contribute:

1. Fork the repository.
2. Create a new branch.
3. Implement your changes.
4. Add or update tests.
5. Submit a pull request.

For major changes, please open an issue first to discuss your proposal.


## Disclaimer

CircuitForge AI is intended for educational, research, and prototyping purposes.

AI-generated circuit designs, simulation results, and verification outputs should not be considered a substitute for professional engineering review.

Always verify circuit designs, component specifications, electrical clearances, and applicable safety requirements before manufacturing or using hardware.

---

**CircuitForge AI — Bringing Artificial Intelligence into Electronic Design Automation.**
