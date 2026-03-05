import sys
import os
import logging
from concurrent import futures

import grpc

# Make generated proto stubs importable
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), "generated"))

from ext_proc.generated.envoy.service.ext_proc.v3 import (
    external_processor_pb2,
    external_processor_pb2_grpc,
)
from ext_proc.generated.envoy.extensions.filters.http.ext_proc.v3 import (
    processing_mode_pb2,
)  # noqa: F401
from ext_proc.scrubber import PiiScrubber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Initialise once at startup – loading the spaCy model is expensive.
_scrubber = PiiScrubber()


class ExtProcService(external_processor_pb2_grpc.ExternalProcessorServicer):
    def Process(self, request_iterator, context):
        """Bidirectional stream handler.

        Envoy sends ProcessingRequest messages; we must reply with a
        ProcessingResponse for each one.  We capture the response Content-Type
        from response_headers so we can route JSON vs plain-text correctly, then
        scrub PII from every response body.
        """
        content_type = ""

        for req in request_iterator:
            msg_type = req.WhichOneof("request")
            log.info("Received request type: %s", msg_type)

            if msg_type == "response_headers":
                # Capture Content-Type for body scrubbing decisions.
                for header in req.response_headers.headers.headers:
                    if header.key.lower() == "content-type":
                        content_type = header.value
                        break
                # Pass headers through unchanged.
                yield external_processor_pb2.ProcessingResponse()

            elif msg_type == "response_body":
                original_body = req.response_body.body
                modified_body = _scrubber.scrub_bytes(original_body, content_type)
                log.info(
                    "Scrubbed response body: %d -> %d bytes",
                    len(original_body),
                    len(modified_body),
                )
                yield external_processor_pb2.ProcessingResponse(
                    response_body=external_processor_pb2.BodyResponse(
                        response=external_processor_pb2.CommonResponse(
                            body_mutation=external_processor_pb2.BodyMutation(
                                body=modified_body
                            )
                        )
                    )
                )
            else:
                # Pass everything else through unchanged
                yield external_processor_pb2.ProcessingResponse()


def serve():
    port = int(os.getenv("GRPC_PORT", "50051"))
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    external_processor_pb2_grpc.add_ExternalProcessorServicer_to_server(
        ExtProcService(), server
    )
    server.add_insecure_port(f"[::]:{port}")
    server.start()
    log.info("ext-proc gRPC server listening on port %d", port)
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
