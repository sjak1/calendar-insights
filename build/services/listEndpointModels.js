/**
 * List Endpoint Models Service
 * Retrieves all models used by a specific endpoint from the Swagger definition
 */
import logger from '../utils/logger.js';
import { loadSwaggerDefinition } from '../utils/swaggerLoader.js';
/**
 * Lists all models used by a specific endpoint from the Swagger definition
 * Priority: CLI --swagger-url > swaggerFilePath parameter
 * @param params Object containing path, method of the endpoint, and optional swaggerFilePath
 * @returns Array of models used by the endpoint
 */
async function listEndpointModels(params) {
    try {
        const { path: endpointPath, method, swaggerFilePath } = params;
        // Load Swagger definition (checks CLI arg, then swaggerFilePath, then env var)
        logger.info(`Loading Swagger definition`);
        const swaggerDefinition = await loadSwaggerDefinition(swaggerFilePath);
        // Check if the endpoint exists
        const paths = swaggerDefinition.paths || {};
        const pathItem = paths[endpointPath];
        if (!pathItem) {
            throw new Error(`Endpoint path '${endpointPath}' not found in Swagger definition`);
        }
        const operation = pathItem[method.toLowerCase()];
        if (!operation) {
            throw new Error(`Method '${method}' not found for endpoint path '${endpointPath}'`);
        }
        // Extract models
        const models = [];
        const processedRefs = new Set();
        // Process request body
        if (operation.requestBody) {
            const content = operation.requestBody.content || {};
            for (const mediaType in content) {
                const mediaTypeObj = content[mediaType];
                if (mediaTypeObj.schema) {
                    extractReferencedModels(mediaTypeObj.schema, models, processedRefs, swaggerDefinition);
                }
            }
        }
        // Process parameters
        if (operation.parameters) {
            for (const parameter of operation.parameters) {
                if (parameter.schema) {
                    extractReferencedModels(parameter.schema, models, processedRefs, swaggerDefinition);
                }
            }
        }
        // Process responses
        if (operation.responses) {
            for (const statusCode in operation.responses) {
                const response = operation.responses[statusCode];
                const content = response.content || {};
                for (const mediaType in content) {
                    const mediaTypeObj = content[mediaType];
                    if (mediaTypeObj.schema) {
                        extractReferencedModels(mediaTypeObj.schema, models, processedRefs, swaggerDefinition);
                    }
                }
            }
        }
        return models;
    }
    catch (error) {
        logger.error(`Error listing endpoint models: ${error.message}`);
        throw error;
    }
}
/**
 * Recursively extracts referenced models from a schema
 */
function extractReferencedModels(schema, models, processedRefs, swaggerDefinition) {
    if (!schema)
        return;
    // Handle $ref
    if (schema.$ref) {
        const ref = schema.$ref;
        if (processedRefs.has(ref))
            return;
        processedRefs.add(ref);
        // Extract model name from reference
        const refParts = ref.split('/');
        const modelName = refParts[refParts.length - 1];
        // Add model to the list
        models.push({
            name: modelName,
            schema: resolveReference(ref, swaggerDefinition)
        });
        // Process the referenced schema to find nested references
        const referencedSchema = resolveReference(ref, swaggerDefinition);
        if (referencedSchema) {
            extractReferencedModels(referencedSchema, models, processedRefs, swaggerDefinition);
        }
    }
    // Handle arrays
    if (schema.type === 'array' && schema.items) {
        extractReferencedModels(schema.items, models, processedRefs, swaggerDefinition);
    }
    // Handle objects with properties
    if (schema.properties) {
        for (const propName in schema.properties) {
            extractReferencedModels(schema.properties[propName], models, processedRefs, swaggerDefinition);
        }
    }
    // Handle allOf, anyOf, oneOf
    ['allOf', 'anyOf', 'oneOf'].forEach(key => {
        if (Array.isArray(schema[key])) {
            schema[key].forEach((subSchema) => {
                extractReferencedModels(subSchema, models, processedRefs, swaggerDefinition);
            });
        }
    });
}
/**
 * Resolves a JSON reference in the Swagger definition
 */
function resolveReference(ref, swaggerDefinition) {
    const refParts = ref.split('/');
    // Remove the first part (#)
    refParts.shift();
    // Navigate through the swagger definition
    let current = swaggerDefinition;
    for (const part of refParts) {
        if (!current[part]) {
            return null;
        }
        current = current[part];
    }
    return current;
}
export default listEndpointModels;
