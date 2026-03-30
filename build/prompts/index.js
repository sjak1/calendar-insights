/**
 * Prompts index file
 * Exports all prompt definitions and handlers
 */
import { addEndpointPrompt, addEndpointArgsSchema, handleAddEndpointPrompt } from './addEndpoint.js';
// Export prompt definitions
export const promptDefinitions = [
    addEndpointPrompt
];
// Export prompt handlers with proper typing
export const promptHandlers = {
    "add-endpoint": {
        schema: addEndpointArgsSchema,
        handler: handleAddEndpointPrompt
    }
};
